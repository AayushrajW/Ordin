"""The signature the sign stage computed and threw away.

Revision ID: 0015_version_signature
Revises: 0014_export_accounting

`_stage_sign` computed a full HMAC-SHA256 and returned `f"signature:{value[:16]}"` as
the job's `output_ref`. Nothing else was stored. There was no signature table, and
`output_ref` is written by `_finish` and read only by `_claim` inside the same module —
so the system recorded that a document was signed while holding nothing that could ever
demonstrate it. Sixty-four bits of a discarded digest, in an internal column nothing
reads.

`SimulatedESignProvider.verify` needs the full value **and** the whole `bound_to`
structure including `signed_at`. Neither survived the stage, so the claim on the record
was unfalsifiable — which is the failure CLAUDE.md's honesty rules name: "Never hide a
stub behind plausible-looking output." `infra/redaction_service.py` already applies the
same reasoning to redaction: "A capability with no persistence path is a capability the
product does not have."

**What is stored is exactly `bound_to`, which is invariant 4's tuple** — case, document,
version, content digest, actor, timestamp. No filename, no title, no content. That is
not a coincidence: a signature that bound anything else would put it on the record.

Append-only, for the reason every attestation here is: a signature that can be rewritten
after the fact attests to nothing. UNIQUE on version_id so a retried stage cannot mint a
second one — the reliability invariant requires that a retry produce no second anchor,
version or derivative, and a signature belongs in that list.
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0015_version_signature"
down_revision: str = "0014_export_accounting"
branch_labels = None
depends_on = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.create_table(
        "version_signature",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("document_version.id"),
            nullable=False, unique=True,
        ),
        # --- the signature itself ---
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.Text(), nullable=False),
        # `provider` and `maturity` are recorded per row rather than assumed, so a
        # signature made by the simulated signer stays distinguishable from one made by
        # whatever replaces it. Reading "SimulatedESignProvider / mvp" off the record is
        # the honest answer to "what signed this".
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("maturity", sa.Text(), nullable=False),
        # --- what it is bound to: invariant 4's tuple, and nothing wider ---
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("signed_at", sa.Text(), nullable=False),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_signature_digest_length"),
    )
    op.create_index("ix_version_signature_case", "version_signature", ["case_id"])

    # Append-only. Only meaningful because ordin_app is not the owner (docs/adr/0001).
    op.execute(f"GRANT SELECT, INSERT ON version_signature TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON version_signature FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_version_signature_case", table_name="version_signature")
    op.drop_table("version_signature")
