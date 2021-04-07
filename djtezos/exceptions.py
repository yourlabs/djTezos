

class DjBlockchainException(Exception):
    pass


class PermanentError(DjBlockchainException):
    pass


class TemporaryError(DjBlockchainException):
    pass
