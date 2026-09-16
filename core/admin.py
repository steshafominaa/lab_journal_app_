from django.contrib import admin
from .models import (
    Profile, Teacher, Subgroup, Assistant, Student,
    LaboratoryWork, Criterion, LabReport, ReportReview,
    Defense, CriterionResult, Attendance, SickLeave,
    DisciplineResult, DisciplineSettings,
)

admin.site.register(Profile)
admin.site.register(Teacher)
admin.site.register(Subgroup)
admin.site.register(Assistant)
admin.site.register(Student)
admin.site.register(LaboratoryWork)
admin.site.register(Criterion)
admin.site.register(LabReport)
admin.site.register(ReportReview)
admin.site.register(Defense)
admin.site.register(CriterionResult)
admin.site.register(Attendance)
admin.site.register(SickLeave)
admin.site.register(DisciplineResult)
admin.site.register(DisciplineSettings)