# Warehouse & Mining Management Application

A full-stack application for managing warehouse and mining operations with Oracle 23ai database.

## Project Structure

```
warehousingandmining/
├── backend/
│   ├── app.py              # Flask application
│   ├── database.py         # Database connection and operations
│   ├── config.py           # Database configuration
│   └── requirements.txt    # Python dependencies
├── frontend/
│   └── index.html          # Tailwind CSS dashboard
└── README.md
```

## Features

- **4 Database Tables**:
  - Customer: Store customer information
  - Product: Manage products and inventory
  - Location: Warehouse and distribution centers
  - Sales: Track sales transactions

- **Backend API** (Flask):
  - Database initialization
  - CRUD operations for all tables
  - Statistics and reporting endpoints
  - CORS enabled for frontend communication

- **Frontend Dashboard** (Tailwind CSS):
  - Beautiful responsive UI
  - One-click database initialization
  - Real-time data display
  - Statistics dashboard
  - Data tables for all entities

## Prerequisites

- Python 3.8+
- Oracle 23ai Database
- Modern web browser

## Installation & Setup

### 1. Backend Setup

```bash
# Navigate to backend folder
cd backend

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Configuration

The backend connects to Oracle 23ai with these credentials:
- Host: 192.168.1.30
- Port: 1521
- Database: dbname-free
- Username: system
- Password: oracle

These can be modified in `backend/config.py` if needed.

### 3. Run the Application

**Terminal 1 - Start Backend Server:**
```bash
cd backend
python app.py
```

The Flask server will start on `http://localhost:5000`

**Terminal 2 - Open Frontend:**
- Open `frontend/index.html` in a web browser, or
- Serve it with a simple HTTP server:
```bash
cd frontend
python -m http.server 8000
```
- Visit `http://localhost:8000` in your browser

## Usage

1. Click the "Initialize Database" button on the dashboard
2. Wait for the success message
3. The application will automatically create 4 tables and populate them with sample data
4. View all data in the respective tables
5. Check statistics at the top of the dashboard

## API Endpoints

- `POST /api/init-database` - Initialize database (create tables & sample data)
- `GET /api/customers` - Get all customers
- `GET /api/products` - Get all products
- `GET /api/locations` - Get all locations
- `GET /api/sales` - Get all sales with details
- `GET /api/stats` - Get statistics

## Database Schema

### Customer Table
- customer_id (PRIMARY KEY)
- customer_name
- email
- phone
- address
- city
- country
- created_date

### Location Table
- location_id (PRIMARY KEY)
- location_name
- city
- country
- latitude
- longitude
- warehouse_type
- created_date

### Product Table
- product_id (PRIMARY KEY)
- product_name
- category
- price
- stock_quantity
- location_id (FOREIGN KEY)
- supplier
- created_date

### Sales Table
- sales_id (PRIMARY KEY)
- customer_id (FOREIGN KEY)
- product_id (FOREIGN KEY)
- quantity
- unit_price
- total_amount
- sales_date
- location_id (FOREIGN KEY)

## Notes

- The application uses oracledb Python library for Oracle database connection
- All tables are created with proper foreign key relationships
- Sample data is automatically populated on initialization
- Frontend data auto-refreshes every 30 seconds
- CORS is enabled to allow frontend-backend communication

## Troubleshooting

**Connection Error to Oracle Database:**
- Verify Oracle 23ai is running on 192.168.1.30:1521
- Check firewall settings
- Confirm credentials in `backend/config.py`

**Port Already in Use:**
- Check if port 5000 (backend) or 8000 (frontend) are in use
- Modify the port in `app.py` if needed

**Frontend Not Showing Data:**
- Ensure backend server is running
- Check browser console for error messages
- Verify CORS is enabled in Flask

## License

This project is open source and available under the MIT License.