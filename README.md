# Student ERP Web Application

A complete Student ERP (Enterprise Resource Planning) system built using Flask and SQLite.  
This project manages student records, attendance, fees, authentication, and data export in a structured and scalable way.

## Features

- User authentication (Admin / Teacher roles)
- Student CRUD operations (Create, Read, Update, Delete)
- Attendance management by class
- Fee tracking and payment status
- Excel data import support
- Duplicate detection system
- CSV export functionality
- Database backup download
- Audit logging for changes
- Student profile management with image upload

## Tech Stack

- Python
- Flask
- Flask-Login
- SQLite
- Pandas
- HTML / CSS / JavaScript
- Chart.js

## Installation

1. Clone the repository
2. Create a virtual environment
3. Install dependencies:

   pip install -r requirements.txt

4. Run the application:

   python app.py

5. Open in browser:

   http://localhost:5000

## Default Admin Login

Username: admin  
Password: admin123  

(Recommended to change after first login.)

## Project Structure

- app.py → Main application logic
- templates/ → HTML templates
- static/ → CSS and JavaScript files
- requirements.txt → Dependencies

## Future Improvements

- Password hashing with stronger security methods
- Role-based access control improvements
- Modular file structure (Blueprints)
- Deployment to cloud hosting
