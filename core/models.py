from django.conf import settings
from django.db import models


# Профиль пользователя. У каждого User из стандартной таблицы Django есть
# один Profile, где хранится роль (студент/ассистент/преподаватель) и отчество.
# Сама роль потом расширяется отдельной таблицей (Teacher/Assistant/Student).
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
    patronymic = models.CharField(max_length=100, blank=True, default='')

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def full_name(self):
        # Собираем ФИО из фамилии, имени и отчества, пропуская пустые поля
        parts = [self.user.last_name, self.user.first_name, self.patronymic]
        return ' '.join(p for p in parts if p) or self.user.username


# Преподаватель. is_admin даёт доступ к разделу "Администрирование" в навбаре.
class Teacher(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    is_admin = models.BooleanField(default=False)

    def __str__(self):
        return self.profile.full_name()


# Подгруппа студентов. У каждой подгруппы один преподаватель.
class Subgroup(models.Model):
    subgroup_name = models.CharField(max_length=20, unique=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, related_name='subgroups')

    def __str__(self):
        return self.subgroup_name

# Ассистент проверяет отчёты студентов своей подгруппы.
class Assistant(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    subgroup = models.ForeignKey(Subgroup, on_delete=models.CASCADE, related_name='assistants')

    def __str__(self):
        return self.profile.full_name()


# Студент относится к одной подгруппе.
class Student(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, primary_key=True)
    subgroup = models.ForeignKey(Subgroup, on_delete=models.CASCADE, related_name='students')

    def __str__(self):
        return self.profile.full_name()

# Лабораторная работа: дедлайны на отчёт и защиту, и веса, с которыми
# оценка за отчёт и оценка за защиту складываются в итоговую оценку за лабу.
class LaboratoryWork(models.Model):
    title = models.CharField(max_length=100, unique=True)
    report_deadline = models.DateField()
    defense_deadline = models.DateField()
    report_weight = models.DecimalField(max_digits=3, decimal_places=2)
    defense_weight = models.DecimalField(max_digits=3, decimal_places=2)

    def __str__(self):
        return self.title


# Критерий оценивания отчёта (например "оформление", "теория") со своим максимумом баллов.
class Criterion(models.Model):
    description = models.CharField(max_length=100, unique=True)
    max_score = models.DecimalField(max_digits=4, decimal_places=2)

    def __str__(self):
        return self.description

# Факт сдачи отчёта студентом по конкретной лабораторной работе (когда сдал).
class LabReport(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='reports')
    lab_work = models.ForeignKey(LaboratoryWork, on_delete=models.CASCADE, related_name='reports')
    submitted_at = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            # у одного студента не может быть двух отчётов по одной и той же лабе
            models.UniqueConstraint(fields=['student', 'lab_work'], name='uq_report_student_lab')
        ]

    def __str__(self):
        return f"{self.student} — {self.lab_work}"

# Проверка отчёта ассистентом. Одна проверка на один отчёт.
class ReportReview(models.Model):
    report = models.OneToOneField(LabReport, on_delete=models.CASCADE, related_name='review')
    assistant = models.ForeignKey(Assistant, on_delete=models.PROTECT, related_name='reviews')
    reviewed_at = models.DateField()
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Проверка отчёта {self.report_id}"


# Защита отчёта у преподавателя: дата защиты, оценка, комментарий.
class Defense(models.Model):
    report = models.OneToOneField(LabReport, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    defense_date = models.DateField(blank=True, null=True)
    score = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Защита — {self.report}"

# Баллы за конкретный критерий в рамках одной проверки отчёта.
class CriterionResult(models.Model):
    review = models.ForeignKey(ReportReview, on_delete=models.CASCADE, related_name='criterion_results')
    criterion = models.ForeignKey(Criterion, on_delete=models.PROTECT, related_name='results')
    score = models.DecimalField(max_digits=4, decimal_places=2, default=0)

    class Meta:
        constraints = [
            # по одному критерию в рамках одной проверки может быть только один результат
            models.UniqueConstraint(fields=['review', 'criterion'], name='uq_review_criterion')
        ]

    def __str__(self):
        return f"{self.criterion} — {self.score}"

# Отметка посещаемости студента на конкретную дату занятия.
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
            # на одну дату у студента может быть только одна отметка
            models.UniqueConstraint(fields=['student', 'lesson_date'], name='uq_attendance_student_date')
        ]

    def __str__(self):
        return f"{self.student} — {self.lesson_date}"


# Загруженная студентом справка о болезни. Преподаватель подтверждает или отклоняет её,
# и от статуса зависит, снимается ли штраф за просрочку (см. grading.py).
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


# Итоги студента по дисциплине: бонусные баллы, оценка за экзамен и согласие
# на "автомат" (получить оценку за экзамен по среднему баллу за лабы).
class DisciplineResult(models.Model):
    student = models.OneToOneField(Student, on_delete=models.CASCADE, primary_key=True)
    bonus_points = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    exam_score = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    auto_pass_agree = models.BooleanField(blank=True, null=True)

    def __str__(self):
        return f"Итоги: {self.student}"

# Общие настройки дисциплины: с каким весом лабы и экзамен входят в итоговую оценку.
class DisciplineSettings(models.Model):
    lab_weight = models.DecimalField(max_digits=3, decimal_places=2)
    exam_weight = models.DecimalField(max_digits=3, decimal_places=2)

    def __str__(self):
        return f"Настройки (лабы: {self.lab_weight}, экзамен: {self.exam_weight})"
