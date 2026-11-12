"""Import batches and the rows they wrote.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.finance.adapters.importers import imports, layouts, undo
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
)
from app.services.finance.service.base import FinanceServiceBase
from app.services.system.jobs import SetLabel

if TYPE_CHECKING:
    from app.services.finance.schemas import ImportPreviewResponse


class ImportsMixin(FinanceServiceBase):
    """Import batches and the rows they wrote."""

    async def get_import_batch(
        self, batch_id: int, *, owner_user_id: int | None = None
    ) -> FinanceImportBatch | None:
        # finance_import_batch.owner_user_id is NOT NULL; standalone uses 0.
        return await imports.get_import_batch(
            self.db,
            batch_id,
            owner_user_id=owner_user_id,
        )

    async def undo_import(
        self, batch: FinanceImportBatch, *, owner_user_id: int | None = None
    ) -> undo.ImportUndone:
        return await undo.undo_import(self.db, batch, owner_user_id=owner_user_id)

    async def list_import_batches(
        self,
        *,
        owner_user_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[FinanceImportBatch]:
        return await imports.list_import_batches(
            self.db,
            owner_user_id=owner_user_id,
            page=page,
            page_size=page_size,
        )

    async def list_import_batch_rows(
        self, batch_id: int
    ) -> list[FinanceImportBatchRow]:
        return await imports.list_import_batch_rows(self.db, batch_id)

    async def preview_file(
        self,
        *,
        owner_user_id: int | None,
        file_name: str | None,
        file_bytes: bytes,
        account_id: int | None = None,
    ) -> imports.ImportPlan:
        return await imports.preview_file(
            self.db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
        )

    async def save_layout(
        self,
        *,
        owner_user_id: int | None,
        file_bytes: bytes,
        name: str,
        columns: dict[str, str],
        date_format: str,
        spending_positive: bool,
    ) -> FinanceImportProfile:
        """An unknown CSV layout, mapped once and kept."""
        return await layouts.save_layout(
            self.db,
            owner_user_id=owner_user_id,
            file_bytes=file_bytes,
            name=name,
            columns=columns,
            date_format=date_format,
            spending_positive=spending_positive,
        )

    async def preview_payload(self, plan: imports.ImportPlan) -> ImportPreviewResponse:
        """A plan as the review shows it, account and category names in."""
        from app.services.finance.adapters.importers.preview import preview_payload

        return await preview_payload(self.db, plan)

    async def remember_account_names(
        self, answers: dict[str, int], *, owner_user_id: int | None
    ) -> None:
        """Keep each review answer on its account: the name a file used for
        it (#620). LookupError when an answer is not your live account."""
        from app.services.finance.adapters.importers import account_names

        await account_names.remember(self.db, answers, owner_user_id=owner_user_id)

    async def import_files(
        self,
        *,
        owner_user_id: int | None,
        file_name: str,
        file_bytes: bytes,
        account_id: int | None = None,
        on_label: SetLabel | None = None,
    ) -> list[imports.ImportResult]:
        """A file, or a .zip of several (#618): each its own import, in
        turn, then the envelopes settled once. The job and the CLI both
        come through here."""
        from app.services.finance.adapters.importers.bundle import files_in
        from app.services.finance.domains.planning.envelope_tags import settle

        results = [
            await imports.import_file(
                self.db,
                owner_user_id=owner_user_id,
                file_name=name,
                file_bytes=body,
                account_id=account_id,
                on_label=on_label,
            )
            for name, body in files_in(file_bytes, file_name)[0]
        ]
        await settle(self.db, owner_user_id=owner_user_id)
        return results

    async def import_file(
        self,
        *,
        owner_user_id: int | None,
        file_name: str | None,
        file_bytes: bytes,
        account_id: int | None = None,
        on_label: SetLabel | None = None,
    ) -> imports.ImportResult:
        from app.services.finance.domains.planning.envelope_tags import settle

        result = await imports.import_file(
            self.db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
            on_label=on_label,
        )
        # Tags arrive with a Quicken import, so an envelope that pays for
        # one may owe for what just came in (#240). After the import's own
        # transfer pass, so a tagged transfer is already known as one.
        # ponytail: the demo seed calls the adapter directly and
        # skip this; the next tag change or import settles them.
        await settle(self.db, owner_user_id=owner_user_id)
        return result
