"""Harness LLM-as-judge (RAG Triad: faithfulness + answer relevance) contra
data/golden_set.json. Herramienta de desarrollo y verificación manual.

Se corre típicamente después de ingestar documentos institucionales:
    python -m scripts.evaluate_rag

Reutiliza hybrid_search con PostgreSQL FTS y el prompt real del Knowledge Agent
(vía PromptManager) para evaluar el comportamiento real del sistema.
"""

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.structured_output import invoke_structured_with_retry
from app.db.session import build_engine, build_sessionmaker
from app.domain.models import AgentRole
from app.schemas.agents import KnowledgeAgentOutput
from app.schemas.evaluation import EvaluationJudgment, EvaluationResult, GoldenSetItem
from app.services.prompt_manager import PromptManager
from app.services.rag_service import (
    build_embeddings_client,
    build_pinecone_client,
    get_index,
    hybrid_search,
)

logger = logging.getLogger(__name__)

_GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_set.json"
_RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "evaluation_results.json"

_JUDGE_SYSTEM_PROMPT = """Sos un evaluador imparcial de un sistema de RAG institucional universitario.

Te dan una pregunta, el contexto que el sistema recupero de la base documental, y la respuesta que genero.

Tu tarea es calificar objetivamente dos metricas entre 0.0 y 1.0:
  1. faithfulness: ¿la respuesta afirma SOLO cosas que estan respaldadas por el contexto recuperado? (1.0 = nada inventado, 0.0 = alucinacion total)
  2. relevance: ¿la respuesta aborda de forma directa y util la pregunta del estudiante? (1.0 = responde exactamente lo que se pregunto, 0.0 = no responde nada)

Se estricto. Justifica brevemente cada puntaje."""


def _load_golden_set() -> list[GoldenSetItem]:
    if not _GOLDEN_SET_PATH.exists():
        return []
    raw = json.loads(_GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    items = [GoldenSetItem(**item) for item in raw]
    real_items = [i for i in items if not i.question.strip().upper().startswith(("PLACEHOLDER", "[PLACEHOLDER]"))]
    skipped = len(items) - len(real_items)
    if skipped:
        logger.warning("evaluate_rag.skipping_placeholders", extra={"count": skipped})
    return real_items


def _format_context(chunks) -> str:
    if not chunks:
        return "(sin resultados)"
    return "\n\n".join(f"[{i}] ({chunk.metadata.source}): {chunk.text}" for i, chunk in enumerate(chunks, start=1))


async def _answer_question(
    question: str, llm: ChatOpenAI, knowledge_prompt: str, index, embeddings_client, sessionmaker, settings: Settings
) -> tuple[str, list[str], str]:
    chunks = await hybrid_search(question, 5, index, embeddings_client, sessionmaker, settings)
    context_block = _format_context(chunks)
    messages = [AIMessage(content=f"Contexto recuperado:\n{context_block}"), HumanMessage(content=question)]
    output = await invoke_structured_with_retry(
        llm, KnowledgeAgentOutput, knowledge_prompt, messages, settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS
    )
    sources = sorted({chunk.metadata.source for chunk in chunks})
    return output.respuesta, sources, context_block


async def _judge(
    question: str, context_block: str, answer: str, llm: ChatOpenAI, settings: Settings
) -> EvaluationJudgment:
    judge_input = f"Pregunta: {question}\n\nContexto recuperado:\n{context_block}\n\nRespuesta generada:\n{answer}"
    return await invoke_structured_with_retry(
        llm,
        EvaluationJudgment,
        _JUDGE_SYSTEM_PROMPT,
        [HumanMessage(content=judge_input)],
        settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    golden_set = _load_golden_set()
    if not golden_set:
        logger.warning("evaluate_rag.empty_golden_set")
        print(f"No hay preguntas reales en {_GOLDEN_SET_PATH} (solo placeholders). Completalo y volve a correr.")
        return

    engine = build_engine(settings)
    sessionmaker = build_sessionmaker(engine)
    pinecone_client = build_pinecone_client(settings)
    index = await get_index(pinecone_client, settings)
    embeddings_client = build_embeddings_client(settings)
    llm = ChatOpenAI(
        model=settings.OPENAI_CHAT_MODEL, api_key=settings.OPENAI_API_KEY.get_secret_value(), temperature=0
    )
    knowledge_prompt = await PromptManager(sessionmaker).get_prompt(AgentRole.KNOWLEDGE.value)

    try:
        results: list[EvaluationResult] = []
        for item in golden_set:
            answer, sources, context_block = await _answer_question(
                item.question, llm, knowledge_prompt, index, embeddings_client, sessionmaker, settings
            )
            judgment = await _judge(item.question, context_block, answer, llm, settings)
            passed = (
                judgment.faithfulness >= settings.EVALUATION_PASS_THRESHOLD
                and judgment.relevance >= settings.EVALUATION_PASS_THRESHOLD
            )
            results.append(
                EvaluationResult(
                    question=item.question,
                    answer=answer,
                    sources_used=sources,
                    expected_source=item.expected_source,
                    faithfulness=judgment.faithfulness,
                    relevance=judgment.relevance,
                    passed=passed,
                )
            )
            print(
                f"{'OK ' if passed else 'FAIL'}  faithfulness={judgment.faithfulness:.2f}  relevance={judgment.relevance:.2f}  {item.question[:70]}"
            )
    finally:
        await index.close()
        await pinecone_client.close()
        await engine.dispose()

    avg_faithfulness = sum(r.faithfulness for r in results) / len(results)
    avg_relevance = sum(r.relevance for r in results) / len(results)
    passed_count = sum(1 for r in results if r.passed)

    print(f"\n{passed_count}/{len(results)} preguntas pasaron (umbral {settings.EVALUATION_PASS_THRESHOLD})")
    print(f"faithfulness promedio: {avg_faithfulness:.2f}  |  relevance promedio: {avg_relevance:.2f}")

    _RESULTS_PATH.write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Detalle guardado en {_RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
