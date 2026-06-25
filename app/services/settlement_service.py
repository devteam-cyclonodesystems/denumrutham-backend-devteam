from app.modules.finance.services.finance_service import FinanceService

class SettlementService(FinanceService):
    """
    Backward-compatibility proxy class redirecting calls 
    to the centralized top-level FinanceService module.
    """
    pass

