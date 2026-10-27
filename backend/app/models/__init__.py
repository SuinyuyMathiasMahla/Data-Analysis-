"""Import every model so that Base.metadata is complete."""
from app.models.analysis import AnalysisResult, AnalysisRun, StatisticalTest, Visualization
from app.models.dataset import CleaningOperation, DataQualityReport, Dataset, DatasetColumn, DatasetVersion, Variable
from app.models.evidence import (Conclusion, ConclusionFinding, Finding, Limitation, Recommendation, RecommendationFinding,
                                 Report, ReportVersion)
from app.models.misc import (AIConversation, AIMessage, AIRecommendation, AuditLog, Notification, ReviewComment, StageReview,
                             SystemSetting)
from app.models.project import Hypothesis, Objective, Project, ProjectMember, ResearchQuestion, ResearchQuestionVariable
from app.models.user import Permission, RefreshToken, Role, RolePermission, User, UserRole, UserToken

__all__ = [
    "AIConversation", "AIMessage", "AIRecommendation", "AnalysisResult", "AnalysisRun", "AuditLog", "CleaningOperation",
    "Conclusion", "ConclusionFinding", "DataQualityReport", "Dataset", "DatasetColumn", "DatasetVersion", "Finding", "Hypothesis",
    "Limitation", "Notification", "Objective", "Permission", "Project", "ProjectMember", "Recommendation",
    "RecommendationFinding", "RefreshToken", "Report", "ReportVersion", "ResearchQuestion", "ResearchQuestionVariable",
    "ReviewComment", "Role", "RolePermission", "StageReview", "StatisticalTest", "SystemSetting", "User", "UserRole", "UserToken",
    "Variable", "Visualization",
]
