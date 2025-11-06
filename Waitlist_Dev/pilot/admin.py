# --- NEW FILE ---
from django.contrib import admin
from .models import PilotSnapshot, EveGroup, EveType

@admin.register(EveGroup)
class EveGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_id')
    search_fields = ('name',)

@admin.register(EveType)
class EveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'type_id', 'group')
    search_fields = ('name',)
    list_filter = ('group',)

# We can also register the snapshot if you want to see it
@admin.register(PilotSnapshot)
class PilotSnapshotAdmin(admin.ModelAdmin):
    list_display = ('character', 'last_updated', 'get_total_sp')
    search_fields = ('character__character_name',)