"""Tests para las funcionalidades avanzadas:
1. Recuperación de jobs de ingesta huérfanos y reintentos.
2. Servicio desacoplado de notificaciones HOTL vía Webhook.
3. Métricas de Prometheus y endpoint /metrics.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.models_orm import IngestionJob
from app.domain.models import (
    ApiKeyScope,
    ContactChannel,
    EscalationPriority,
    EscalationType,
    FileType,
    TaskStatus,
)
from app.main import app
from app.schemas.escalation import EscalationTicketResponse
from app.services.ingestion_worker import recover_orphaned_jobs
from app.services.notification_service import HOTLNotificationService


@pytest.mark.asyncio
async def test_hotl_notification_service_webhook_success(test_settings: Settings):
    """Verifica el envío exitoso de notificaciones HOTL a un webhook externo."""
    webhook_url = "https://secretaria.universidad.edu.ar/api/tickets-webhook"
    test_settings.HOTL_WEBHOOK_URL = webhook_url
    test_settings.HOTL_NOTIFICATION_ENABLED = True

    service = HOTLNotificationService(test_settings)
    ticket = EscalationTicketResponse(
        ticket_id=uuid4(),
        thread_id="test-thread-123",
        original_question="¿Cómo solicito equivalencias?",
        relevant_history=[],
        reason="No encontrado en RAG",
        escalation_type=EscalationType.NO_INFO_FOUND,
        priority=EscalationPriority.MEDIUM,
        contact_channel=ContactChannel.EMAIL,
        contact_value="alumno@test.edu",
        status=TaskStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post(webhook_url).respond(status_code=200, json={"status": "received"})
        sent = await service.notify_ticket_created(ticket)
        assert sent is True


@pytest.mark.asyncio
async def test_hotl_notification_service_handles_http_error(test_settings: Settings):
    """Verifica que el servicio de notificación capture errores HTTP sin propagar excepciones."""
    webhook_url = "https://secretaria.universidad.edu.ar/api/tickets-webhook"
    test_settings.HOTL_WEBHOOK_URL = webhook_url
    test_settings.HOTL_NOTIFICATION_ENABLED = True

    service = HOTLNotificationService(test_settings)
    ticket = EscalationTicketResponse(
        ticket_id=uuid4(),
        thread_id="test-thread-456",
        original_question="¿Cuándo inician las clases?",
        relevant_history=[],
        reason="Consulta compleja",
        escalation_type=EscalationType.REQUIRES_HUMAN_ACTION,
        priority=EscalationPriority.HIGH,
        contact_channel=ContactChannel.WHATSAPP,
        contact_value="+5491100000000",
        status=TaskStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post(webhook_url).respond(status_code=500)
        sent = await service.notify_ticket_created(ticket)
        assert sent is False


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_requeues_and_fails_max_retries(db_sessionmaker, test_settings: Settings):
    """Verifica la recuperación y reintento de jobs de ingesta colgados en PROCESSING."""
    mock_redis = AsyncMock()
    now = datetime.now(UTC)
    old_time = now - timedelta(minutes=test_settings.INGESTION_JOB_TIMEOUT_MINUTES + 5)

    job_recoverable_id = uuid4()
    job_exhausted_id = uuid4()

    async with db_sessionmaker() as session:
        # Job 1: 0 reintentos -> debe ser re-encolado en PENDING
        job_1 = IngestionJob(
            job_id=job_recoverable_id,
            filename="reglamento.pdf",
            file_type=FileType.PDF.value,
            storage_path="data/uploads/test1.pdf",
            status=TaskStatus.PROCESSING.value,
            retry_count=0,
            started_at=old_time,
        )
        # Job 2: max reintentos alcanzado -> debe ser marcado como FAILED
        job_2 = IngestionJob(
            job_id=job_exhausted_id,
            filename="plan.docx",
            file_type=FileType.DOCX.value,
            storage_path="data/uploads/test2.docx",
            status=TaskStatus.PROCESSING.value,
            retry_count=test_settings.INGESTION_MAX_RETRIES,
            started_at=old_time,
        )
        session.add_all([job_1, job_2])
        await session.commit()

    recovered = await recover_orphaned_jobs(db_sessionmaker, mock_redis, test_settings)
    assert recovered == 2

    # Verificar que Redis rpush fue llamado para el job recuperable
    mock_redis.rpush.assert_awaited_once_with(test_settings.REDIS_INGEST_QUEUE_KEY, str(job_recoverable_id))

    async with db_sessionmaker() as session:
        j1 = await session.get(IngestionJob, job_recoverable_id)
        assert j1.status == TaskStatus.PENDING.value
        assert j1.retry_count == 1

        j2 = await session.get(IngestionJob, job_exhausted_id)
        assert j2.status == TaskStatus.FAILED.value
        assert "tiempo límite" in j2.error_message


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_unit(test_settings: Settings):
    """Prueba unitaria pura de la lógica de reintento/timeout sin requerir Postgres real."""
    mock_redis = AsyncMock()
    now = datetime.now(UTC)
    old_time = now - timedelta(minutes=test_settings.INGESTION_JOB_TIMEOUT_MINUTES + 5)

    job_recoverable = IngestionJob(
        job_id=uuid4(),
        filename="reglamento.pdf",
        file_type=FileType.PDF.value,
        storage_path="data/uploads/test1.pdf",
        status=TaskStatus.PROCESSING.value,
        retry_count=0,
        started_at=old_time,
    )
    job_exhausted = IngestionJob(
        job_id=uuid4(),
        filename="plan.docx",
        file_type=FileType.DOCX.value,
        storage_path="data/uploads/test2.docx",
        status=TaskStatus.PROCESSING.value,
        retry_count=test_settings.INGESTION_MAX_RETRIES,
        started_at=old_time,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [job_recoverable, job_exhausted]
    mock_session.execute.return_value = mock_result
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    class _MockSessionMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    recovered = await recover_orphaned_jobs(_MockSessionMaker(), mock_redis, test_settings)
    assert recovered == 2
    assert job_recoverable.status == TaskStatus.PENDING.value
    assert job_recoverable.retry_count == 1
    assert job_exhausted.status == TaskStatus.FAILED.value
    assert "tiempo límite" in job_exhausted.error_message
    mock_redis.rpush.assert_awaited_once_with(test_settings.REDIS_INGEST_QUEUE_KEY, str(job_recoverable.job_id))


def test_prometheus_metrics_endpoint():
    """Verifica que el endpoint /metrics requiera scope ADMIN y exponga métricas en formato estándar."""
    from app.core.security import get_current_api_key
    from app.db.models_orm import ApiKey
    from app.db.session import get_db_session

    async def _mock_db():
        yield MagicMock()

    app.dependency_overrides[get_db_session] = _mock_db
    app.state.rate_limiter = MagicMock(check=AsyncMock(return_value=MagicMock(allowed=True)))
    client = TestClient(app)

    try:
        # 1. Petición sin credenciales debe ser rechazada con 401
        unauthorized = client.get("/metrics")
        assert unauthorized.status_code == 401

        # 2. Petición con scope CLIENT debe ser rechazada con 403
        client_key = ApiKey(key_id=uuid4(), scope=ApiKeyScope.CLIENT.value, name="test-client")
        app.dependency_overrides[get_current_api_key] = lambda: client_key
        forbidden = client.get("/metrics", headers={"X-API-Key": "test-client-key"})
        assert forbidden.status_code == 403

        # 3. Petición con scope ADMIN autorizada (200 OK)
        admin_key = ApiKey(key_id=uuid4(), scope=ApiKeyScope.ADMIN.value, name="test-admin")
        app.dependency_overrides[get_current_api_key] = lambda: admin_key
        response = client.get("/metrics", headers={"X-API-Key": "test-admin-key"})
        assert response.status_code == 200
        assert "http_requests_total" in response.text
        assert "hotl_tickets_total" in response.text
        assert "ingestion_jobs_total" in response.text
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_api_key, None)
