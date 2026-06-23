from typing import Any, Awaitable, Callable, Optional

from .cap_client import CapClient, CapEvent, Negotiation, Order

ParseFn = Callable[[dict], Any]
WorkFn = Callable[[Any], Awaitable[Any]]
PrecheckFn = Callable[[Any], Awaitable[None]]


class ProviderRuntime:
    def __init__(self, cap: CapClient, service_id: str,
                 parse_fn: ParseFn, work_fn: WorkFn, *,
                 precheck_fn: Optional[PrecheckFn] = None,
                 fund_address: Optional[str] = None,
                 upload_threshold: int = 200_000):
        self.cap = cap
        self.service_id = service_id
        self.parse_fn = parse_fn
        self.work_fn = work_fn
        self.precheck_fn = precheck_fn
        self.fund_address = fund_address
        self.upload_threshold = upload_threshold

    def install(self) -> None:
        self.cap.on(CapEvent.NEGOTIATION_CREATED, self._on_negotiation)
        self.cap.on(CapEvent.ORDER_PAID, self._on_paid)

    async def run(self) -> None:
        self.install()
        await self.cap.connect()
        await self.cap.run_forever()

    async def _on_negotiation(self, neg: Negotiation) -> None:
        if neg.service_id != self.service_id:
            return
        try:
            req = self.parse_fn(neg.requirements)
        except Exception as exc:
            await self.cap.reject_negotiation(
                neg.negotiation_id, reason=f"invalid request: {exc}")
            return
        if self.precheck_fn is not None:
            try:
                await self.precheck_fn(req)
            except Exception as exc:
                await self.cap.reject_negotiation(
                    neg.negotiation_id, reason=str(exc))
                return
        await self.cap.accept_negotiation(
            neg.negotiation_id, fund_address=self.fund_address)

    async def _on_paid(self, order: Order) -> None:
        if order.service_id != self.service_id:
            return
        try:
            req = self.parse_fn(order.requirements)
            deliverable = await self.work_fn(req)
            payload = deliverable.model_dump(mode="json")
            body = deliverable.model_dump_json().encode("utf-8")
            file_url = None
            if len(body) > self.upload_threshold:
                file_url = await self.cap.upload_file(
                    body, f"{order.order_id}.json")
            await self.cap.deliver_order(
                order.order_id, payload, file_url=file_url)
        except Exception as exc:
            await self.cap.reject_order(order.order_id, reason=str(exc))
