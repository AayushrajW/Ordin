"""Full-text search over OCR text and case references.

Revision ID: 0010_search
Revises: 0009_accounts

CLAUDE.md already decided the retrieval path: "Postgres full-text search is the
retrieval path", with pgvector, OpenSearch and hybrid search explicitly not in this
build. This adds the index that makes it usable.

**The `simple` configuration, not `english`.** The corpus is bilingual — Tesseract runs
`hin+eng` — and an English stemmer applied to Devanagari does nothing useful while
mangling English-transliterated Hindi words. `simple` does no stemming and no stop-word
removal, so "the" is searchable and "investigating" does not match "investigate". That
is a real loss, taken deliberately: silently dropping Hindi from a bilingual system's
search would be worse, and it is honest about what the index does rather than appearing
to understand both languages.

**No index on `extracted_field.value`.** Those rows carry names, phone numbers and
addresses. A search index over them is an index of victims and witnesses, and the
disclosure class exists precisely to keep derived text away from a grantee
(`infra/disclosure.py`, threat VIC-01). Field values remain reachable only through the
document routes that gate them.

The index is on the expression the query uses. If the two ever drift the index is simply
not used and search gets slow, rather than wrong — but `api/search.py` and this file
must be changed together.
"""
from alembic import op

revision: str = "0010_search"
down_revision: str = "0009_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_ocr_text_fts ON ocr_text "
        "USING GIN (to_tsvector('simple', text))"
    )
    # Case references are short and matched by prefix and substring, which a tsvector
    # does not help with. trigram would; it needs an extension nobody has approved, so
    # the reference search is a plain ILIKE over a small table and says so.
    op.execute("CREATE INDEX ix_case_record_reference ON case_record (reference)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_case_record_reference")
    op.execute("DROP INDEX IF EXISTS ix_ocr_text_fts")
