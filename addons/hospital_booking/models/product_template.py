from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_medical_service = fields.Boolean(
        string="Es servicio médico",
        compute="_compute_is_medical_service",
        search="_search_is_medical_service",
    )

    @api.depends("categ_id")
    def _compute_is_medical_service(self):
        categ = self.env.ref(
            "hospital_booking.product_category_medical_service",
            raise_if_not_found=False,
        )
        categ_id = categ.id if categ else 0
        for rec in self:
            rec.is_medical_service = rec.categ_id.id == categ_id

    def _search_is_medical_service(self, operator, value):
        categ = self.env.ref(
            "hospital_booking.product_category_medical_service",
            raise_if_not_found=False,
        )
        categ_id = categ.id if categ else 0
        if (operator == "=" and value) or (operator == "!=" and not value):
            return [("categ_id", "=", categ_id)]
        return [("categ_id", "!=", categ_id)]
