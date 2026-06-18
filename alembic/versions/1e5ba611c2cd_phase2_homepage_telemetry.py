"""phase2_homepage_telemetry

Revision ID: 1e5ba611c2cd
Revises: 299d311faeaa
Create Date: 2026-06-18 15:09:24.652497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e5ba611c2cd'
down_revision: Union[str, Sequence[str], None] = '299d311faeaa'
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
            "'CLAIM_TEMPLE_CLICK', 'TEMPLE_VIEW'"
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
            "'CHECKOUT_STARTED', 'CHECKOUT_COMPLETED'"
            ")"
        )
