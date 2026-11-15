# 📚 E-Library Management System

A full-stack, cloud-ready digital library and book marketplace application built with **Python**, **Flask**, and **SQLite/MySQL**. The platform enables users to discover, read, rent, and purchase books with an integrated reader timer, email OTP authentication, and Razorpay checkout.

---

## 🌟 Key Features

### 👤 User Capabilities
- **Secure Registration & Login**: Email verification via OTP (SMTP) and password hashing with `bcrypt`.
- **Password Recovery**: Secure tokenized password reset links sent via email.
- **Book Discovery**: Filter books by category (`Frontend`, `Backend`, `Stories`, `Kids`, `Geography`), keyword search, and popularity.
- **In-Browser PDF Reader**:
  - Embedded PDF reader with page navigation.
  - Interactive **Reading Timer** tracking active minutes and calculating rental cost.
  - Notes taking and automated summary PDF generation.
- **E-Commerce & Payment**:
  - Cart management and Single-Item "Buy Now".
  - Seamless Razorpay payment gateway integration.
- **Wishlist**: Toggle books in and out of personal wishlist.
- **User Profile**: Edit username, address, contact details, and upload custom profile pictures.

### 🛡️ Admin Capabilities
- **Dedicated Admin Portal**: Separate authentication flow and dashboard with live metrics (total books, categories).
- **Book Catalog Management**: Upload books with title, price, quantity, category, description, cover image, and PDF attachment.
- **Automated Text Extraction**: Reads and parses uploaded PDF files with `PyPDF2`.
- **Publisher Overview**: View, inspect, and manage books uploaded by administrators.
- **Profile Updates**: Manage admin avatar and contact info.

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials.

### 3. Run Application
```bash
python app.py
```
Open browser at: `http://localhost:5000`

### 4. Default Admin Login
- **URL**: `http://localhost:5000/adminlogin`
- **Email**: `admin@gmail.com`
- **Password**: `admin123`
