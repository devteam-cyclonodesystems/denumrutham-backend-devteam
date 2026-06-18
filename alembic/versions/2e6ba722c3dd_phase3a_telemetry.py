"""phase3a_telemetry

Revision ID: 2e6ba722c3dd
Revises: 1e5ba611c2cd
Create Date: 2026-06-18 17:35:12.124567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e6ba722c3dd'
down_revision: Union[str, Sequence[str], None] = '1e5ba611c2cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("portal_analytics_events") as batch_op:
        batch_op.drop_constraint("chk_portal_event_name", type_="check")
        batch_op.create_check_constraint(
            "chk_portal_event_name",
            "event_name IN ("
            "'BOOK_POOJA_CLICK', 'OFFERING_CLICK', 'STORE_CLICK', "
            "'FOLLOW_CLICK', 'AD_CLICK', 'RECOMMENDATION_CLICK', "
            "'CHECKOUT_STARTED', 'CHECKOUT_COMPLETED', "
            "'HOMEPAGE_SEARCH', 'POPULAR_CHIP_CLICK', 'TEMPLE_CARD_CLICK', "
            "'FESTIVAL_CLICK', 'CAROUSEL_SCROLL', 'SUGGEST_TEMPLE_CLICK', "
            "'CLAIM_TEMPLE_CLICK', 'TEMPLE_VIEW', "
            "'CLAIM_CTA_IMPRESSION', 'CLAIM_SUBMISSION', 'CLAIM_APPROVED'"
            ")"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("portal_analytics_events") as batch_op:
        batch_op.drop_constraint("chk_portal_event_name", type_="check")
        batch_op.create_check_constraint(
            "chk_portal_event_name",
            "event_name IN ("
            "'BOOK_POOJA_CLICK', 'OFFERING_CLICK', 'STORE_CLICK', "
            "'FOLLOW_CLICK', 'AD_CLICK', 'RECOMMENDATION_CLICK', "
            "'CHECKOUT_STARTED', 'CHECKOUT_COMPLETED', "
            "'HOMEPAGE_SEARCH', 'POPULAR_CHIP_CLICK', 'TEMPLE_CARD_CLICK', "
            "'FESTIVAL_CLICK', 'CAROUSEL_SCROLL', 'SUGGEST_TEMPLE_CLICK', "
            "'CLAIM_TEMPLE_CLICK', 'TEMPLE_VIEW'"
            ")"
        )
