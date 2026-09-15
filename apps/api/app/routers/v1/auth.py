"""Signup, login, logout, and who-am-I. Routers wire dependencies to services and nothing more."""

from fastapi import APIRouter, Request, Response, status

from app.core.cookies import clear_auth_cookies, set_auth_cookies
from app.core.request_ip import client_ip
from app.deps.auth import CurrentUser, RedisClient, SessionId
from app.deps.db import DbSession
from app.schemas.auth import LoginRequest, SignupRequest, UserResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest, request: Request, response: Response, db: DbSession, redis: RedisClient
) -> UserResponse:
    user, session_id, csrf_token = await auth_service.signup(
        db,
        redis,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        ip=client_ip(request),
    )
    set_auth_cookies(response, session_id, csrf_token)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession, redis: RedisClient
) -> UserResponse:
    user, session_id, csrf_token = await auth_service.login(
        db, redis, email=body.email, password=body.password, ip=client_ip(request)
    )
    set_auth_cookies(response, session_id, csrf_token)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, redis: RedisClient, session_id: SessionId) -> None:
    await auth_service.logout(redis, session_id)
    clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
