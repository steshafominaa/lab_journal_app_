from django.conf import settings
from django.db import models


class Profile(models.Model):
    ROLE_CHOICES = [
        ('student', 'Студент'),
        ('assistant', 'Ассистент'),
        ('teacher', 'Преподаватель'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class Teacher(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    is_admin = models.BooleanField(default=False)

    def __str__(self):
        return self.profile.user.get_full_name() or self.profile.user.username


class Subgroup(models.Model):
    subgroup_name = models.CharField(max_length=20, unique=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, related_name='subgroups')

    def __str__(self):
        return self.subgroup_name

class Assistant(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    subgroup = models.ForeignKey(Subgroup, on_delete=models.CASCADE, related_name='assistants')

    def __str__(self):
        return self.profile.user.get_full_name() or self.profile.user.username


class Student(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    subgroup = models.ForeignKey(Subgroup, on_delete=models.CASCADE, related_name='students')

    def __str__(self):
        return self.profile.user.get_full_name() or self.profile.user.username

class LaboratoryWork(models.Model):
    title = models.CharField(max_length=100, unique=True)
    report_deadline = models.DateField()
    defense_deadline = models.DateField()
    report_weight = models.DecimalField(max_digits=3, decimal_places=2)
    defense_weight = models.DecimalField(max_digits=3, decimal_places=2)

    def __str__(self):
        return self.title


class Criterion(models.Model):
    description = models.CharField(max_length=100, unique=True)
    max_score = models.DecimalField(max_digits=4, decimal_places=2)

    def __str__(self):
        return self.description

class LabReport(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='reports')
    lab_work = models.ForeignKey(LaboratoryWork, on_delete=models.CASCADE, related_name='reports')
    submitted_at = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'lab_work'], name='uq_report_student_lab')
        ]

    def __str__(self):
        return f"{self.student} — {self.lab_work}"

class ReportReview(models.Model):
    report = models.OneToOneField(LabReport, on_delete=models.CASCADE, related_name='review')
    assistant = models.ForeignKey(Assistant, on_delete=models.PROTECT, related_name='reviews')
    reviewed_at = models.DateField()
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Проверка отчёта {self.report_id}"


class Defense(models.Model):
    report = models.OneToOneField(LabReport, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    defense_date = models.DateField(blank=True, null=True)
    score = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Защита — {self.report}"

class CriterionResult(models.Model):
    review = models.ForeignKey(ReportReview, on_delete=models.CASCADE, related_name='criterion_results')
    criterion = models.ForeignKey(Criterion, on_delete=models.PROTECT, related_name='results')
    score = models.DecimalField(max_digits=4, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['review', 'criterion'], name='uq_review_criterion')
        ]

    def __str__(self):
        return f"{self.criterion} — {self.score}"

class Attendance(models.Model):
    STATUS_CHOICES = [
        ('П', 'Присутствовал'),
        ('Н', 'Не был'),
        ('Б', 'Болел'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance')
    lesson_date = models.DateField()
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'lesson_date'], name='uq_attendance_student_date')
        ]

    def __str__(self):
        return f"{self.student} — {self.lesson_date}"


class SickLeave(models.Model):
    STATUS_CHOICES = [
        ('на рассмотрении', 'На рассмотрении'),
        ('подтверждена', 'Подтверждена'),
        ('отклонена', 'Отклонена'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='sick_leaves')
    file = models.FileField(upload_to='sick_leaves/')
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='на рассмотрении')

    def __str__(self):
        return f"Справка {self.student} — {self.status}"


class DisciplineResult(models.Model):
    student = models.OneToOneField(Student, on_delete=models.CASCADE, primary_key=True)
    bonus_points = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    exam_score = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    auto_pass_agree = models.BooleanField(blank=True, null=True)

    def __str__(self):
        return f"Итоги: {self.student}"

class DisciplineSettings(models.Model):
    lab_weight = models.DecimalField(max_digits=3, decimal_places=2)
    exam_weight = models.DecimalField(max_digits=3, decimal_places=2)

    def __str__(self):
        return f"Настройки (лабы: {self.lab_weight}, экзамен: {self.exam_weight})"