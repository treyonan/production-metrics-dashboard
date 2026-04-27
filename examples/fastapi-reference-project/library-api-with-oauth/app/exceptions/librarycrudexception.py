class LibraryCRUDException(Exception):
    """Custom exception for library CRUD operations"""
    def __init__(self, message: str, error_type: str = "validation_error"):
        self.message = message
        self.error_type = error_type
        super().__init__(self.message)