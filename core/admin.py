from django.contrib import admin
from .models import (
    Profile, Teacher, Subgroup, Assistant, Student,
    LaboratoryWork, Criterion, LabReport, ReportReview,
    Defense, CriterionResult, Attendance, SickLeave,
    DisciplineResult, DisciplineSettings,
)


class LaboratoryWorkAdmin(admin.ModelAdmin):
    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        last = LaboratoryWork.objects.order_by('-pk').first()
        if last:
            initial.setdefault('report_weight', last.report_weight)
            initial.setdefault('defense_weight', last.defense_weight)
        return initial


admin.site.register(Profile)
admin.site.register(Teacher)
admin.site.register(Subgroup)
admin.site.register(Assistant)
admin.site.register(Student)
admin.site.register(LaboratoryWork, LaboratoryWorkAdmin)
admin.site.register(Criterion)
admin.site.register(LabReport)
admin.site.register(ReportReview)
admin.site.register(Defense)
admin.site.register(CriterionResult)
admin.site.register(Attendance)
admin.site.register(SickLeave)
admin.site.register(DisciplineResult)
admin.site.register(DisciplineSettings)