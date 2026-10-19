from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("add/", views.add, name="add"),
    path("glucose/", views.glucose_detail, name="glucose"),
    path("weight/", views.weight_detail, name="weight"),
    path("pressure/", views.bp_detail, name="pressure"),
    path("history/", views.history, name="history"),
    path("schedules/", views.schedules, name="schedules"),
    path("schedules/new/", views.schedule_edit, name="schedule_new"),
    path("schedules/<uuid:pk>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedules/<uuid:pk>/delete/", views.schedule_delete, name="schedule_delete"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/2fa/", views.two_factor, name="two_factor"),
    path("settings/restore/", views.restore, name="restore"),
    path("export/json/", views.export_json, name="export_json"),
    path("export/pdf/", views.export_pdf, name="export_pdf"),
    path("scheduler/tick/", views.tick, name="tick"),
    path("<str:kind>/edit/<uuid:pk>/", views.edit, name="edit"),
    path("<str:kind>/delete/<uuid:pk>/", views.delete, name="delete"),
]
