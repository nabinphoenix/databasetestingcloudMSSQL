# Lab Guide: Signup/Login App with AWS RDS SQL Server, FastAPI, and Admin Panel

**Course:** Designing and Developing Applications on the Cloud (DDAC)  
**Lab:** Week 7 - Database  
**Stack:** AWS RDS SQL Server, Python, FastAPI, pyodbc, plain HTML/CSS/JS

## 1. Overview

This lab builds a simple full-stack web app where:

- Users can sign up and sign in through a plain HTML/CSS/JS frontend.
- User data is stored in an AWS RDS SQL Server database.
- A Python FastAPI backend handles signup, login, JWT authentication, and admin routes.
- An admin panel lets an admin user view registered users and LMS data.
- Passwords are hashed with bcrypt and are never stored in plain text.
- The app uses pyodbc for SQL Server database access.

## Architecture

```text
Browser
  index.html, admin.html, welcome.html
        |
        | fetch() calls over HTTP
        v
FastAPI backend
  main.py, database.py, auth.py
        |
        | pyodbc + ODBC Driver 18
        v
AWS RDS SQL Server
  myapp database
```

## Important Note About boto3

`boto3` is the AWS SDK for managing AWS resources such as RDS, S3, and EC2. It is not used to query SQL Server data from this application.

This app uses `pyodbc` for runtime database access, which is the correct tool for connecting to SQL Server.

## 2. Prerequisites

- AWS account or AWS Academy Learner Lab access.
- AWS CLI configured.
- Python 3.10 or newer.
- SQL Server Management Studio (SSMS) or another SQL Server client.
- Microsoft ODBC Driver 18 for SQL Server installed.

Check AWS CLI access:

```powershell
aws sts get-caller-identity
```

## 3. Provision AWS RDS SQL Server

All AWS CLI commands below are PowerShell-friendly.

### 3.1 Create a security group

```powershell
aws ec2 create-security-group --group-name mssql-sg --description "SQL Server RDS access"
```

Save the returned `GroupId`. You will use it when allowing database access and creating the RDS instance.

### 3.2 Find your public IP address

```powershell
(Invoke-WebRequest -uri "http://checkip.amazonaws.com" -UseBasicParsing).Content.Trim()
```

### 3.3 Allow SQL Server traffic from your IP

```powershell
aws ec2 authorize-security-group-ingress --group-id YOUR_SECURITY_GROUP_ID --protocol tcp --port 1433 --cidr "YOUR_IP/32"
```

Replace:

- `YOUR_SECURITY_GROUP_ID` with your security group ID.
- `YOUR_IP` with your public IP address.

Using `/32` allows only your current IP address to access the database.

### 3.4 Check the DB subnet group

```powershell
aws rds describe-db-subnet-groups
```

Most AWS Academy Learner Lab accounts already include a `default` DB subnet group.

### 3.5 Create the RDS SQL Server instance

```powershell
aws rds create-db-instance --db-instance-identifier myapp-mssql --db-instance-class db.t3.micro --engine sqlserver-ex --engine-version 15.00.4153.1.v1 --master-username admin --master-user-password "ChangeThisPassword123!" --allocated-storage 20 --vpc-security-group-ids YOUR_SECURITY_GROUP_ID --db-subnet-group-name default --publicly-accessible --license-model license-included
```

This usually takes 5-10 minutes.

### 3.6 Check the RDS status

```powershell
aws rds describe-db-instances --db-instance-identifier myapp-mssql --query "DBInstances[0].DBInstanceStatus" --output text
```

Wait until the status is:

```text
available
```

You can also wait automatically:

```powershell
aws rds wait db-instance-available --db-instance-identifier myapp-mssql
```

### 3.7 Get the RDS endpoint

```powershell
aws rds describe-db-instances --db-instance-identifier myapp-mssql --query "DBInstances[0].Endpoint.Address" --output text
```

Save this endpoint. It goes into `backend/.env` as `DB_HOST`.

## 4. Database Setup in SSMS

Open SQL Server Management Studio and connect to the RDS instance.

Connection details:

- **Server name:** your RDS endpoint followed by `,1433`
- **Authentication:** SQL Server Authentication
- **Login:** `admin`
- **Password:** the master password used when creating the RDS instance
- **Connection Properties:** enable **Trust server certificate**

Do not use "Browse for Servers". Type the RDS endpoint manually.

Create a database named:

```text
myapp
```

Create the required application tables in that database. The app uses these tables:

| Table | Purpose |
|---|---|
| `users` | Stores registered users, bcrypt password hashes, roles, profile images, and descriptions |
| `courses` | Stores LMS course titles, descriptions, and assigned teachers |
| `course_enrollments` | Stores which students are enrolled in which courses |

The backend also includes startup-safe checks that can add missing LMS columns and tables when API routes run.

For admin access, create or register a user first, then set that user's admin flag in SSMS.

## 5. Project Structure

```text
backend/
  main.py
  database.py
  auth.py
  .env.example
  requirements.txt

frontend/
  index.html
  admin.html
  welcome.html
  style.css

README.md
```

## 6. Backend Setup

Open PowerShell from the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install Microsoft ODBC Driver 18 for SQL Server if it is not already installed:

```text
https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
```

Use the x64 driver for a normal 64-bit Windows and 64-bit Python setup.

## 7. Configure Environment Variables

Create `backend/.env` from the example file:

```powershell
Copy-Item .env.example .env
```

Fill in:

```text
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_NAME=myapp
DB_USER=admin
DB_PASSWORD=your_database_password
JWT_SECRET=replace-with-a-long-random-secret
```

Generate a random JWT secret in PowerShell:

```powershell
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})
```

The real `.env` file is ignored by Git and should not be committed.

## 8. Run the Backend

From the `backend` folder:

```powershell
uvicorn main:app --reload --port 8000
```

Expected output:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Health check:

```text
http://127.0.0.1:8000/
```

Expected response:

```json
{ "status": "ok" }
```

## 9. API Reference

| Method | Endpoint | Auth required | Description |
|---|---|---|---|
| GET | `/` | No | Health check |
| POST | `/api/signup` | No | Register a new user |
| POST | `/api/login` | No | Authenticate user and return JWT |
| GET | `/api/users/me` | Yes | Get current user profile |
| PUT | `/api/users/me/description` | Yes | Update current user's description |
| GET | `/api/users/{user_id}/image` | No | Load profile image |
| GET | `/api/lms/overview` | Yes | Show courses for current role |
| GET | `/api/admin/users` | Yes, admin | List registered users |
| GET | `/api/admin/lms` | Yes, admin | List LMS courses, teachers, and students |
| POST | `/api/admin/courses` | Yes, admin | Create course |
| PUT | `/api/admin/courses/{course_id}` | Yes, admin | Update course |
| POST | `/api/admin/enrollments` | Yes, admin | Enroll student in course |
| POST | `/api/admin/demo-data` | Yes, admin | Insert demo LMS data |

## 10. Frontend Setup

Open a second PowerShell terminal:

```powershell
cd frontend
python -m http.server 5800
```

Open:

```text
http://127.0.0.1:5800/index.html
```

Avoid opening the HTML files directly with `file://`. Serving the frontend over HTTP makes local testing more reliable.

## 11. Test the Flow

1. Open `index.html`.
2. Register a user with email, password, role, description, and optional profile image.
3. Login with the same email and password.
4. Normal users go to `welcome.html`.
5. Admin users go to `admin.html`.
6. In the admin panel, view users, add demo data, create courses, assign teachers, and enroll students.
7. Logout and login as a student or teacher to see role-based dashboard data.

## 12. Demo Accounts

If demo data is inserted through the admin panel, the demo users use this password:

```text
Password123!
```

Demo users include teacher and student accounts such as:

```text
maya.teacher@cloudlms.local
arjun.teacher@cloudlms.local
sita.student@cloudlms.local
ravi.student@cloudlms.local
mina.student@cloudlms.local
bibek.student@cloudlms.local
anjali.student@cloudlms.local
```

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| PowerShell error like `Unexpected token` | Bash-style command continuation was used | Write AWS CLI commands on one line in PowerShell |
| `ModuleNotFoundError: No module named 'pyodbc'` | Python dependencies are missing | Run `pip install -r requirements.txt` inside `backend` |
| SSMS certificate error | RDS certificate is not trusted locally | Enable **Trust server certificate** |
| Login says invalid credentials | Password hash does not match typed password | Register through the app or update the hash correctly |
| `409 Conflict` on signup | Email already exists | Use a new email or login with the existing account |
| Frontend not updating after CSS/JS changes | Browser cache | Press `Ctrl + F5` |
| Favicon 404 in logs | No favicon file is included | Harmless for this lab |

## 14. Security Notes

- This project is for lab/demo use.
- Do not commit `backend/.env`.
- Do not expose your database to `0.0.0.0/0`.
- Restrict RDS security group access to your IP only for the lab.
- In production, use HTTPS, a secrets manager, restricted CORS, and a backend server inside the VPC.
- Passwords are hashed with bcrypt before storage.

## 15. Cleanup

When the lab is complete, delete the RDS instance if you no longer need it:

```powershell
aws rds delete-db-instance --db-instance-identifier myapp-mssql --skip-final-snapshot
```

This helps avoid ongoing AWS charges in personal AWS accounts.
