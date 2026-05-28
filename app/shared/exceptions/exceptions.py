class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code

class BusinessException(AppException):
    def __init__(self, message: str = "Business Rule Violation"):
        super().__init__(message, 422)

class NotFoundException(AppException):
    def __init__(self, message: str = "Not Found"):
        super().__init__(message, 404)

class ForbiddenError(AppException):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, 403)

class ServiceException(AppException):
    def __init__(self, message: str, code: str, status_code: int = 400):
        super().__init__(message, status_code)
        self.code = code


