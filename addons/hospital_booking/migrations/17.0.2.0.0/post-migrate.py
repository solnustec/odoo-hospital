"""Post-migration: assign medical services category to existing products."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Find the category ID
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'hospital_booking'
          AND name = 'product_category_medical_service'
          AND model = 'product.category'
    """)
    row = cr.fetchone()
    if not row:
        _logger.warning("Medical service category not found, skipping migration")
        return

    categ_id = row[0]

    # Migrate products linked to doctors
    cr.execute("""
        UPDATE product_template
        SET categ_id = %s
        WHERE id IN (
            SELECT DISTINCT pp.product_tmpl_id
            FROM hr_employee_booking_service_rel rel
            JOIN product_product pp ON pp.id = rel.product_id
        ) AND categ_id != %s
    """, (categ_id, categ_id))
    count = cr.rowcount
    if count:
        _logger.info("Migrated %d product templates to medical services category", count)

    # Also migrate any service-type products with 'Consulta' in name
    cr.execute("""
        UPDATE product_template
        SET categ_id = %s
        WHERE type = 'service'
          AND categ_id != %s
          AND (name->>'en_US' LIKE 'Consulta%%' OR name->>'es_EC' LIKE 'Consulta%%')
    """, (categ_id, categ_id))
    count2 = cr.rowcount
    if count2:
        _logger.info("Migrated %d additional Consulta templates to medical services category", count2)
