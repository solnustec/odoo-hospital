{
    "name": "Hospital Booking",
    "version": "17.0.1.0.0",
    "category": "Services",
    "summary": "Appointment booking system for hospital management",
    "description": """
        Appointment scheduling with doctor availability, calendar integration,
        and lifecycle management. Designed to work standalone or with the
        hospital_chatbot module for WhatsApp booking.
    """,
    "author": "Solnus",
    "website": "https://www.solnustec.com",
    "depends": ["base", "hr", "resource", "calendar", "product"],
    "data": [
        "security/booking_security.xml",
        "security/ir.model.access.csv",
        "data/booking_data.xml",
        "data/booking_demo.xml",
        "views/appointment_views.xml",
        "views/hr_employee_views.xml",
        "views/booking_config_views.xml",
        "views/menu.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "auto_install": False,
    "application": True,
}
