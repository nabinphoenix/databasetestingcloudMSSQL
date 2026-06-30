from typing import Optional

import pyodbc
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import create_access_token, hash_password, verify_password, verify_token
from database import DatabaseConfigError, get_connection


app = FastAPI(title="Simple Signup/Login API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None


class DescriptionRequest(BaseModel):
    description: Optional[str] = ""


class CourseRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    teacher_id: int


class EnrollmentRequest(BaseModel):
    course_id: int
    student_id: int


ALLOWED_ROLES = {"student", "teacher", "admin"}
MAX_IMAGE_SIZE = 1024 * 1024
DEMO_PASSWORD = "Password123!"


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def validate_credentials(email_value: Optional[str], password_value: Optional[str]) -> tuple[str, str]:
    email = normalize_email(email_value)
    password = password_value or ""

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required.",
        )

    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )

    return email, password


def validate_auth_request(payload: AuthRequest) -> tuple[str, str]:
    return validate_credentials(payload.email, payload.password)


def validate_role(role_value: Optional[str]) -> str:
    role = (role_value or "student").strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be student, teacher, or admin.",
        )
    return role


async def read_profile_image(profile_image: Optional[UploadFile]) -> tuple[Optional[bytes], Optional[str]]:
    if profile_image is None or not profile_image.filename:
        return None, None

    content_type = profile_image.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile image must be an image file.",
        )

    image_bytes = await profile_image.read()
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile image must be 1 MB or smaller.",
        )

    return image_bytes, content_type


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        return verify_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def ensure_lms_columns(cursor) -> None:
    cursor.execute(
        """
        IF COL_LENGTH('users', 'role') IS NULL
            ALTER TABLE users ADD role NVARCHAR(50) DEFAULT 'student'
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('users', 'profile_image') IS NULL
            ALTER TABLE users ADD profile_image VARBINARY(MAX) NULL
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('users', 'profile_image_content_type') IS NULL
            ALTER TABLE users ADD profile_image_content_type NVARCHAR(100) NULL
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('users', 'description') IS NULL
            ALTER TABLE users ADD description NVARCHAR(1000) NULL
        """
    )
    cursor.execute(
        """
        IF OBJECT_ID('courses', 'U') IS NULL
            CREATE TABLE courses (
                id INT IDENTITY(1,1) PRIMARY KEY,
                title NVARCHAR(255) NOT NULL,
                description NVARCHAR(1000) NULL,
                teacher_id INT NOT NULL,
                created_at DATETIME DEFAULT GETDATE(),
                CONSTRAINT FK_courses_teacher FOREIGN KEY (teacher_id) REFERENCES users(id)
            )
        """
    )
    cursor.execute(
        """
        IF OBJECT_ID('course_enrollments', 'U') IS NULL
            CREATE TABLE course_enrollments (
                id INT IDENTITY(1,1) PRIMARY KEY,
                course_id INT NOT NULL,
                student_id INT NOT NULL,
                enrolled_at DATETIME DEFAULT GETDATE(),
                CONSTRAINT FK_enrollments_course FOREIGN KEY (course_id) REFERENCES courses(id),
                CONSTRAINT FK_enrollments_student FOREIGN KEY (student_id) REFERENCES users(id),
                CONSTRAINT UQ_course_student UNIQUE (course_id, student_id)
            )
        """
    )
    cursor.execute(
        """
        UPDATE users
        SET role = CASE WHEN is_admin = 1 THEN 'admin' ELSE 'student' END
        WHERE role IS NULL
        """
    )
    cursor.connection.commit()


def require_admin(current_user: dict) -> None:
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required.",
        )


def fetch_role_options(cursor) -> dict:
    cursor.execute(
        """
        SELECT id, email, role
        FROM users
        WHERE role IN ('student', 'teacher')
        ORDER BY role, email
        """
    )
    students = []
    teachers = []
    for row in cursor.fetchall():
        item = {"id": row.id, "email": row.email}
        if row.role == "teacher":
            teachers.append(item)
        else:
            students.append(item)
    return {"students": students, "teachers": teachers}


def serialize_course(row) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "teacher_id": row.teacher_id,
        "teacher_email": row.teacher_email,
        "student_count": row.student_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.post("/api/signup")
async def signup(
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("student"),
    description: str = Form(""),
    profile_image: Optional[UploadFile] = File(default=None),
):
    email, password = validate_credentials(email, password)
    user_role = validate_role(role)
    password_hash = hash_password(password)
    image_bytes, image_content_type = await read_profile_image(profile_image)
    is_admin = user_role == "admin"

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    password_hash,
                    is_admin,
                    role,
                    description,
                    profile_image,
                    profile_image_content_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                email,
                password_hash,
                is_admin,
                user_role,
                description.strip() or None,
                pyodbc.Binary(image_bytes) if image_bytes else None,
                image_content_type,
            )
            conn.commit()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc
    except pyodbc.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc

    return {"message": "Account created successfully.", "role": user_role}


@app.post("/api/login")
def login(payload: AuthRequest):
    email, password = validate_auth_request(payload)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT id, email, password_hash, is_admin, role
                FROM users
                WHERE email = ?
                """,
                email,
            )
            row = cursor.fetchone()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    if not row or not verify_password(password, row.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user = {
        "id": row.id,
        "email": row.email,
        "is_admin": bool(row.is_admin),
        "role": row.role or ("admin" if row.is_admin else "student"),
    }
    token = create_access_token(user)

    return {"token": token, "user": user}


@app.get("/api/users/me")
def get_my_profile(current_user: dict = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT id, email, is_admin, role, description, created_at,
                       CASE WHEN profile_image IS NULL THEN 0 ELSE 1 END AS has_image
                FROM users
                WHERE id = ?
                """,
                current_user["id"],
            )
            row = cursor.fetchone()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile was not found.",
        )

    created_at = row.created_at.isoformat() if row.created_at else None
    return {
        "id": row.id,
        "email": row.email,
        "is_admin": bool(row.is_admin),
        "role": row.role or ("admin" if row.is_admin else "student"),
        "description": row.description or "",
        "created_at": created_at,
        "has_image": bool(row.has_image),
        "image_url": f"/api/users/{row.id}/image" if row.has_image else None,
    }


@app.put("/api/users/me/description")
def update_my_description(
    payload: DescriptionRequest,
    current_user: dict = Depends(get_current_user),
):
    description = (payload.description or "").strip()
    if len(description) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Description must be 1000 characters or fewer.",
        )

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                UPDATE users
                SET description = ?
                WHERE id = ?
                """,
                description or None,
                current_user["id"],
            )
            conn.commit()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"message": "Description updated.", "description": description}


@app.get("/api/lms/overview")
def get_lms_overview(current_user: dict = Depends(get_current_user)):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT c.id, c.title, c.description, c.teacher_id, t.email AS teacher_email,
                       c.created_at, COUNT(e.id) AS student_count
                FROM courses c
                INNER JOIN users t ON t.id = c.teacher_id
                LEFT JOIN course_enrollments e ON e.course_id = c.id
                WHERE (
                    ? = 'student' AND EXISTS (
                        SELECT 1
                        FROM course_enrollments se
                        WHERE se.course_id = c.id AND se.student_id = ?
                    )
                )
                OR (? = 'teacher' AND c.teacher_id = ?)
                OR (? = 'admin')
                GROUP BY c.id, c.title, c.description, c.teacher_id, t.email, c.created_at
                ORDER BY c.created_at DESC, c.id DESC
                """,
                current_user.get("role"),
                current_user["id"],
                current_user.get("role"),
                current_user["id"],
                current_user.get("role"),
            )
            rows = cursor.fetchall()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"courses": [serialize_course(row) for row in rows]}


@app.get("/api/users/{user_id}/image")
def get_user_image(user_id: int):
    from fastapi.responses import Response

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT profile_image, profile_image_content_type
                FROM users
                WHERE id = ?
                """,
                user_id,
            )
            row = cursor.fetchone()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    if not row or not row.profile_image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    return Response(
        content=bytes(row.profile_image),
        media_type=row.profile_image_content_type or "image/jpeg",
    )


@app.get("/api/admin/users")
def list_users(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT id, email, is_admin, role, description, created_at,
                       CASE WHEN profile_image IS NULL THEN 0 ELSE 1 END AS has_image
                FROM users
                ORDER BY created_at DESC, id DESC
                """
            )
            rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT COALESCE(role, CASE WHEN is_admin = 1 THEN 'admin' ELSE 'student' END) AS role,
                       COUNT(*) AS total
                FROM users
                GROUP BY COALESCE(role, CASE WHEN is_admin = 1 THEN 'admin' ELSE 'student' END)
                """
            )
            role_rows = cursor.fetchall()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    users = []
    for row in rows:
        created_at = row.created_at.isoformat() if row.created_at else None
        role = row.role or ("admin" if row.is_admin else "student")
        users.append(
            {
                "id": row.id,
                "email": row.email,
                "role": role,
                "is_admin": bool(row.is_admin),
                "description": row.description or "",
                "created_at": created_at,
                "has_image": bool(row.has_image),
                "image_url": f"/api/users/{row.id}/image" if row.has_image else None,
            }
        )

    stats = {"student": 0, "teacher": 0, "admin": 0, "total": len(users)}
    for row in role_rows:
        stats[row.role] = row.total

    return {"users": users, "stats": stats}


@app.get("/api/admin/lms")
def get_admin_lms(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT c.id, c.title, c.description, c.teacher_id, t.email AS teacher_email,
                       c.created_at, COUNT(e.id) AS student_count
                FROM courses c
                INNER JOIN users t ON t.id = c.teacher_id
                LEFT JOIN course_enrollments e ON e.course_id = c.id
                GROUP BY c.id, c.title, c.description, c.teacher_id, t.email, c.created_at
                ORDER BY c.created_at DESC, c.id DESC
                """
            )
            courses = [serialize_course(row) for row in cursor.fetchall()]
            options = fetch_role_options(cursor)
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"courses": courses, **options}


@app.post("/api/admin/courses")
def create_course(payload: CourseRequest, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    title = payload.title.strip()
    description = (payload.description or "").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Course title is required.")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE id = ? AND role = 'teacher'
                """,
                payload.teacher_id,
            )
            if cursor.fetchone()[0] == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Course teacher must be a registered teacher.",
                )
            cursor.execute(
                """
                INSERT INTO courses (title, description, teacher_id)
                VALUES (?, ?, ?)
                """,
                title,
                description or None,
                payload.teacher_id,
            )
            conn.commit()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"message": "Course created."}


@app.put("/api/admin/courses/{course_id}")
def update_course(
    course_id: int,
    payload: CourseRequest,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    title = payload.title.strip()
    description = (payload.description or "").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Course title is required.")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE id = ? AND role = 'teacher'
                """,
                payload.teacher_id,
            )
            if cursor.fetchone()[0] == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Course teacher must be a registered teacher.",
                )
            cursor.execute(
                """
                UPDATE courses
                SET title = ?, description = ?, teacher_id = ?
                WHERE id = ?
                """,
                title,
                description or None,
                payload.teacher_id,
                course_id,
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
            conn.commit()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"message": "Course updated."}


@app.post("/api/admin/enrollments")
def enroll_student(payload: EnrollmentRequest, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE id = ? AND role = 'student'
                """,
                payload.student_id,
            )
            if cursor.fetchone()[0] == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Enrollment user must be a registered student.",
                )
            cursor.execute(
                """
                INSERT INTO course_enrollments (course_id, student_id)
                VALUES (?, ?)
                """,
                payload.course_id,
                payload.student_id,
            )
            conn.commit()
    except pyodbc.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student is already enrolled in this course or the course does not exist.",
        ) from exc
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {"message": "Student enrolled."}


@app.post("/api/admin/demo-data")
def seed_demo_data(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    demo_users = [
        ("maya.teacher@cloudlms.local", "teacher", "Cloud computing teacher who guides RDS and backend labs."),
        ("arjun.teacher@cloudlms.local", "teacher", "Application development teacher for frontend and API integration."),
        ("sita.student@cloudlms.local", "student", "Student enrolled in cloud database and LMS practice courses."),
        ("ravi.student@cloudlms.local", "student", "Student learning FastAPI, SQL Server, and frontend integration."),
    ]

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ensure_lms_columns(cursor)
            password_hash = hash_password(DEMO_PASSWORD)

            for email, role, description in demo_users:
                cursor.execute("SELECT id FROM users WHERE email = ?", email)
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """
                    INSERT INTO users (email, password_hash, is_admin, role, description)
                    VALUES (?, ?, 0, ?, ?)
                    """,
                    email,
                    password_hash,
                    role,
                    description,
                )

            cursor.execute("SELECT id FROM users WHERE email = ?", "maya.teacher@cloudlms.local")
            maya_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM users WHERE email = ?", "arjun.teacher@cloudlms.local")
            arjun_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM users WHERE email = ?", "sita.student@cloudlms.local")
            sita_id = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM users WHERE email = ?", "ravi.student@cloudlms.local")
            ravi_id = cursor.fetchone()[0]

            demo_courses = [
                ("AWS RDS SQL Server Basics", "Create tables, connect with ODBC, and store LMS records in AWS RDS.", maya_id),
                ("FastAPI Backend Integration", "Build API routes for signup, login, courses, and enrollments.", arjun_id),
                ("Frontend LMS Dashboard", "Use plain HTML, CSS, and JavaScript to show dynamic database data.", arjun_id),
            ]

            for title, description, teacher_id in demo_courses:
                cursor.execute("SELECT id FROM courses WHERE title = ?", title)
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """
                    INSERT INTO courses (title, description, teacher_id)
                    VALUES (?, ?, ?)
                    """,
                    title,
                    description,
                    teacher_id,
                )

            enrollments = [
                ("AWS RDS SQL Server Basics", sita_id),
                ("AWS RDS SQL Server Basics", ravi_id),
                ("FastAPI Backend Integration", sita_id),
                ("Frontend LMS Dashboard", ravi_id),
            ]
            for course_title, student_id in enrollments:
                cursor.execute("SELECT id FROM courses WHERE title = ?", course_title)
                course_id = cursor.fetchone()[0]
                try:
                    cursor.execute(
                        """
                        INSERT INTO course_enrollments (course_id, student_id)
                        VALUES (?, ?)
                        """,
                        course_id,
                        student_id,
                    )
                except pyodbc.IntegrityError:
                    pass

            conn.commit()
    except DatabaseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database is not configured: {exc}",
        ) from exc

    return {
        "message": "Demo LMS users, courses, and enrollments are ready.",
        "demo_password": DEMO_PASSWORD,
    }
