from __future__ import annotations

from ..llm import LLM
from ..schemas import FormatDeliverable, FormatRequest, Reference

FORMAT_SYS = (
    "You are a writing specialist. Given verified findings, produce a polished, "
    "well-structured report in markdown in the requested style and for the given "
    "audience. Use numbered references and cite them inline as [n]. "
    'Respond ONLY with JSON: {"report_markdown": str, "references": [{"n": int, '
    '"url": str, "title": str}, ...]}.'
)


def make_format_work(llm: LLM):
    async def work(req: FormatRequest) -> FormatDeliverable:
        data = await llm.generate_json(system=FORMAT_SYS, user=req.model_dump_json())
        return FormatDeliverable(
            report_markdown=data.get("report_markdown", ""),
            references=[Reference.model_validate(r) for r in data.get("references", [])])
    return work
