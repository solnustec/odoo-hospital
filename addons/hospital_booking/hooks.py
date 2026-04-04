import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Assign medical services category to existing service products linked to doctors."""
    categ = env.ref(
        "hospital_booking.product_category_medical_service",
        raise_if_not_found=False,
    )
    if not categ:
        return

    env.cr.execute("""
        SELECT DISTINCT pp.product_tmpl_id
        FROM hr_employee_booking_service_rel rel
        JOIN product_product pp ON pp.id = rel.product_id
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE pt.categ_id != %s
    """, (categ.id,))
    tmpl_ids = [row[0] for row in env.cr.fetchall()]

    if tmpl_ids:
        env["product.template"].browse(tmpl_ids).write({"categ_id": categ.id})
        _logger.info(
            "Migrated %d product templates to medical services category",
            len(tmpl_ids),
        )
