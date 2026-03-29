"""Tests for hospital.booking.config model."""

from odoo.tests import tagged

from .common import BookingTestCommon


@tagged("post_install", "-at_install")
class TestBookingConfig(BookingTestCommon):

    def test_get_config_returns_existing(self):
        """get_config returns existing config for the company."""
        config1 = self.env["hospital.booking.config"].get_config()
        config2 = self.env["hospital.booking.config"].get_config()
        self.assertEqual(config1.id, config2.id)

    def test_get_config_creates_if_missing(self):
        """get_config creates a new config if none exists."""
        new_company = self.env["res.company"].create({"name": "Test Company"})
        config = self.env["hospital.booking.config"].get_config(new_company.id)
        self.assertTrue(config.exists())
        self.assertEqual(config.company_id.id, new_company.id)

    def test_default_values(self):
        """Config has sensible defaults."""
        config = self.config
        self.assertEqual(config.default_slot_duration, 30)
        self.assertEqual(config.buffer_between_appointments, 15)
        self.assertEqual(config.min_advance_booking_hours, 2)
        self.assertEqual(config.max_advance_booking_days, 60)
        self.assertTrue(config.auto_confirm)
        self.assertEqual(config.max_appointments_per_patient_day, 3)
        self.assertEqual(config.max_pending_per_patient, 5)
        self.assertEqual(config.max_no_shows_before_block, 3)
        self.assertEqual(config.free_cancellation_hours, 24)

    def test_unique_constraint(self):
        """Only one config per company."""
        with self.assertRaises(Exception):
            self.env["hospital.booking.config"].create({
                "company_id": self.env.company.id,
            })
