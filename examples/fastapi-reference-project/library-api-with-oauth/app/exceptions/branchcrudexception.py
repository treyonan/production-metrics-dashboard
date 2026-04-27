class BranchCRUDException(Exception):
    """Custom exception for branch CRUD operations"""
    def __init__(self, message: str, error_type: str = "validation_error"):
        self.message = message
        self.error_type = error_type
        super().__init__(self.message)