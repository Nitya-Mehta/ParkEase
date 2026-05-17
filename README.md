# ParkEase

ParkEase is a Django-based smart parking management system for managing parking slots, booking requests, vehicle scans, complaints, and admin operations in one place.

Live site: [park-ease-gilt.vercel.app](https://park-ease-gilt.vercel.app)

## Features

- User registration, login, and profile management
- Parking slot browsing and booking
- Admin slot management and request approval
- Vehicle scan flow with ANPR support
- Complaint submission and resolution
- Pass/subscription flow with Razorpay checkout
- Area-based dashboards and admin scoping

## Tech Stack

- Python 3
- Django 5
- PostgreSQL
- WhiteNoise for static files
- Razorpay for payments
- OpenCV and RapidOCR for vehicle plate scanning

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with the required environment variables.
4. Run migrations:

```bash
python manage.py migrate
```

5. Start the development server:

```bash
python manage.py runserver
```

## Deployment

This project is configured for deployment on Vercel with static files collected via WhiteNoise.

## Notes

- SQLite is fine for local development, but production should use PostgreSQL.
- Do not commit `.env`, `db.sqlite3`, or virtual environment folders to GitHub.

