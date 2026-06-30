# Simple LMS Signup/Login App With Admin Panel

This project demonstrates a complete connection between a plain frontend, a FastAPI backend, and an AWS RDS SQL Server database.

It is a small LMS-style system where users can register, login, choose a role, upload a profile image, edit descriptions, create courses, assign teachers, enroll students, and view dynamic data stored in the database.

## Stack

- Backend: Python, FastAPI, `pyodbc`
- Database: AWS RDS SQL Server
- Driver: ODBC Driver 18 for SQL Server
- Frontend: Plain HTML, CSS, vanilla JavaScript
- Auth: JWT with `PyJWT`
- Password security: `bcrypt`
- File upload: Profile images stored directly in SQL Server as `VARBINARY(MAX)`

This project does not use SQLAlchemy, boto3, Node.js, Express, React, Vue, or any build tool.

## Project Structure

```text
backend/
  main.py
  database.py
  auth.py
  .env
  .env.example
  requirements.txt

frontend/
  index.html
  admin.html
  welcome.html
  style.css
```

## Features

- User registration with email, password, role, description, and optional profile image
- Roles: `student`, `teacher`, `admin`
- Passwords are hashed before storing in the database
- Login returns a JWT token
- Users can update their own profile description from the frontend
- Admins can create and update courses from the frontend
- Admins can assign a teacher to a course
- Admins can enroll students into courses
- Admins can insert demo teachers, students, courses, and enrollments
- Dashboard pages show live data loaded from SQL Server
- Profile images are retrieved dynamically from the backend
- CORS is enabled for local lab testing

## Database Schema

Create the `users` table:

```sql
CREATE TABLE users (
  id INT IDENTITY(1,1) PRIMARY KEY,
  email NVARCHAR(255) UNIQUE NOT NULL,
  password_hash NVARCHAR(255) NOT NULL,
  is_admin BIT DEFAULT 0,
  role NVARCHAR(50) DEFAULT 'student',
  description NVARCHAR(1000) NULL,
  profile_image VARBINARY(MAX) NULL,
  profile_image_content_type NVARCHAR(100) NULL,
  created_at DATETIME DEFAULT GETDATE()
);
```

Create the `courses` table:

```sql
CREATE TABLE courses (
  id INT IDENTITY(1,1) PRIMARY KEY,
  title NVARCHAR(255) NOT NULL,
  description NVARCHAR(1000) NULL,
  teacher_id INT NOT NULL,
  created_at DATETIME DEFAULT GETDATE(),
  CONSTRAINT FK_courses_teacher FOREIGN KEY (teacher_id) REFERENCES users(id)
);
```

Create the `course_enrollments` table:

```sql
CREATE TABLE course_enrollments (
  id INT IDENTITY(1,1) PRIMARY KEY,
  course_id INT NOT NULL,
  student_id INT NOT NULL,
  enrolled_at DATETIME DEFAULT GETDATE(),
  CONSTRAINT FK_enrollments_course FOREIGN KEY (course_id) REFERENCES courses(id),
  CONSTRAINT FK_enrollments_student FOREIGN KEY (student_id) REFERENCES users(id),
  CONSTRAINT UQ_course_student UNIQUE (course_id, student_id)
);
```

The backend also tries to create the new LMS columns and tables automatically when an API route runs. If your table already exists, you can run this migration manually:

```sql
IF COL_LENGTH('users', 'role') IS NULL
  ALTER TABLE users ADD role NVARCHAR(50) DEFAULT 'student';

IF COL_LENGTH('users', 'description') IS NULL
  ALTER TABLE users ADD description NVARCHAR(1000) NULL;

IF COL_LENGTH('users', 'profile_image') IS NULL
  ALTER TABLE users ADD profile_image VARBINARY(MAX) NULL;

IF COL_LENGTH('users', 'profile_image_content_type') IS NULL
  ALTER TABLE users ADD profile_image_content_type NVARCHAR(100) NULL;

IF OBJECT_ID('courses', 'U') IS NULL
  CREATE TABLE courses (
    id INT IDENTITY(1,1) PRIMARY KEY,
    title NVARCHAR(255) NOT NULL,
    description NVARCHAR(1000) NULL,
    teacher_id INT NOT NULL,
    created_at DATETIME DEFAULT GETDATE(),
    CONSTRAINT FK_courses_teacher FOREIGN KEY (teacher_id) REFERENCES users(id)
  );

IF OBJECT_ID('course_enrollments', 'U') IS NULL
  CREATE TABLE course_enrollments (
    id INT IDENTITY(1,1) PRIMARY KEY,
    course_id INT NOT NULL,
    student_id INT NOT NULL,
    enrolled_at DATETIME DEFAULT GETDATE(),
    CONSTRAINT FK_enrollments_course FOREIGN KEY (course_id) REFERENCES courses(id),
    CONSTRAINT FK_enrollments_student FOREIGN KEY (student_id) REFERENCES users(id),
    CONSTRAINT UQ_course_student UNIQUE (course_id, student_id)
  );

UPDATE users
SET role = CASE WHEN is_admin = 1 THEN 'admin' ELSE 'student' END
WHERE role IS NULL;
```

## Sample SQL Queries

Show all users:

```sql
SELECT id, email, role, description, created_at
FROM users
ORDER BY created_at DESC;
```

Show all courses with teachers:

```sql
SELECT c.id, c.title, c.description, t.email AS teacher_email, c.created_at
FROM courses c
INNER JOIN users t ON t.id = c.teacher_id
ORDER BY c.created_at DESC;
```

Show student enrollments:

```sql
SELECT c.title AS course_title, s.email AS student_email, e.enrolled_at
FROM course_enrollments e
INNER JOIN courses c ON c.id = e.course_id
INNER JOIN users s ON s.id = e.student_id
ORDER BY e.enrolled_at DESC;
```

Make an existing user an admin:

```sql
UPDATE users
SET is_admin = 1, role = 'admin'
WHERE email = 'admin@example.com';
```

## Demo Data

Login as an admin, open `admin.html`, then click `Add Demo Data`.

This inserts demo users:

```text
maya.teacher@cloudlms.local
arjun.teacher@cloudlms.local
sita.student@cloudlms.local
ravi.student@cloudlms.local
```

The demo password is:

```text
Password123!
```

It also inserts sample courses and enrollments:

- AWS RDS SQL Server Basics
- FastAPI Backend Integration
- Frontend LMS Dashboard

## Backend Setup

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

Create the backend environment file:

```powershell
Copy-Item .env.example .env
```

Fill in `backend/.env`:

```text
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
JWT_SECRET=replace-with-a-long-random-secret
```

Run the backend:

```powershell
uvicorn main:app --reload --port 8000
```

Health check:

```text
http://localhost:8000/
```

Expected response:

```json
{ "status": "ok" }
```

## Frontend Setup

Open a second PowerShell terminal:

```powershell
cd frontend
python -m http.server 5800
```

Open the frontend in a browser:

```text
http://localhost:5800/index.html
```

The frontend API URL is set at the top of each page script:

```javascript
const API_BASE_URL = "http://localhost:8000/api";
```

## Pages

`index.html`

- Register a new LMS account
- Choose role: student, teacher, or admin
- Add a short profile description
- Upload a profile image
- Login with email and password

`welcome.html`

- Shows the logged-in user's email, role, join date, profile image, and description
- Lets the user update their description
- Students see enrolled courses
- Teachers see assigned courses
- Admins see all courses

`admin.html`

- Admin-only page
- Shows total users, students, teachers, and admins
- Displays registered users from SQL Server
- Shows profile images stored in the database
- Creates or updates courses
- Assigns teachers to courses
- Enrolls students into courses
- Adds demo LMS data

## API Routes

```text
GET  /
POST /api/signup
POST /api/login
GET  /api/users/me
PUT  /api/users/me/description
GET  /api/users/{user_id}/image
GET  /api/lms/overview
GET  /api/admin/users
GET  /api/admin/lms
POST /api/admin/courses
PUT  /api/admin/courses/{course_id}
POST /api/admin/enrollments
POST /api/admin/demo-data
```

## Expected Behavior

- `200 OK` on successful signup
- `409 Conflict` if the same email is registered again
- `200 OK` on successful login
- `403 Forbidden` if a non-admin user tries to access an admin route
- `401 Unauthorized` if the JWT token is missing or invalid

## Notes

- Database queries use raw parameterized SQL with `?` placeholders.
- Frontend changes are dynamic: when descriptions, courses, teachers, or enrollments are changed, the database is updated through FastAPI.
- Profile images are stored in SQL Server for simplicity in this lab.
- For a production app, storing images in S3 and saving only the image URL/key in SQL Server is usually better.
- JWT tokens expire after 1 day.
- The favicon `404` in the frontend server log is harmless because this project does not include a favicon file.
