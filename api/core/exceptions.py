class AppError(Exception):
    message = "Application error."

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class NotFoundError(AppError): ...


class ConflictError(AppError): ...


class ForbiddenError(AppError): ...


class ExternalServiceError(AppError): ...


class UnauthorizedError(AppError): ...


class UnprocessableError(AppError): ...


class InternalError(AppError):
    message = "An internal error occurred."


class UserNotFound(NotFoundError):
    message = "User not found."


class UsernameAlreadyExists(ConflictError):
    message = "Username already exists."


class EmailAlreadyExists(ConflictError):
    message = "Email already exists."


class UserAlreadyExists(ConflictError):
    message = "Username or email already exists."


class NotAuthorized(ForbiddenError):
    message = "Not authorized to perform this action."


class InvalidCredentials(UnauthorizedError):
    message = "Incorrect username or password."


class NotAuthenticated(UnauthorizedError):
    message = "Could not validate credentials."
