"""Servicio desacoplado de notificaciones para eventos HOTL (Human-on-the-Loop).

Permite alertar en tiempo real a los operadores de Secretaría/Bedelía (mediante
webhooks HTTP, mensajería o endpoints externos) ante la creación de nuevos tickets
de escalamiento, sin bloquear ni interrumpir el flujo principal de la conversación.
"""

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas.escalation import EscalationTicketResponse

logger = logging.getLogger(__name__)


class HOTLNotificationService:
    """Envía notificaciones asíncronas de tickets HOTL a servicios externos."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def notify_ticket_created(self, ticket: EscalationTicketResponse) -> bool:
        """Dispara un webhook HTTP asíncrono hacia el endpoint configurado."""
        if not self._settings.HOTL_NOTIFICATION_ENABLED:
            logger.debug("hotl_notification.disabled")
            return False

        webhook_url = self._settings.HOTL_WEBHOOK_URL
        if not webhook_url or not webhook_url.strip():
            logger.debug("hotl_notification.no_webhook_url_configured")
            return False

        payload: dict[str, Any] = {
            "event": "hotl.ticket_created",
            "ticket_id": str(ticket.ticket_id),
            "thread_id": ticket.thread_id,
            "original_question": ticket.original_question,
            "contact_channel": ticket.contact_channel.value,
            "contact_value": ticket.contact_value,
            "priority": ticket.priority.value,
            "escalation_type": ticket.escalation_type.value,
            "reason": ticket.reason,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.HOTL_NOTIFICATION_TIMEOUT_SECONDS) as client:
                response = await client.post(webhook_url, json=payload)
                if response.is_success:
                    logger.info(
                        "hotl_notification.sent_successfully",
                        extra={"ticket_id": str(ticket.ticket_id), "status_code": response.status_code},
                    )
                    return True
                logger.warning(
                    "hotl_notification.server_returned_error",
                    extra={"ticket_id": str(ticket.ticket_id), "status_code": response.status_code},
                )
                return False
        except httpx.HTTPError as exc:
            logger.error(
                "hotl_notification.http_error",
                extra={"ticket_id": str(ticket.ticket_id), "error": str(exc)},
            )
            return False
        except Exception as exc:  # noqa: BLE001 - Evita que un error inesperado de red interrumpa la creación del ticket
            logger.error(
                "hotl_notification.unexpected_error",
                extra={"ticket_id": str(ticket.ticket_id), "error": str(exc)},
            )
            return False
