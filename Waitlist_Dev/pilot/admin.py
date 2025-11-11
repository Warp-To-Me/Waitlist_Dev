from django.contrib import admin
from .models import PilotSnapshot, EveGroup, EveType, EveCategory

@admin.register(EveCategory)
class EveCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_id', 'published')
    search_fields = ('name',)
    list_filter = ('published',)

@admin.register(EveGroup)
class EveGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_id', 'category', 'published')
    search_fields = ('name',)
    list_filter = ('published', 'category__name')
    autocomplete_fields = ('category',) # Add autocomplete

@admin.register(EveType)
class EveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'type_id', 'group', 'meta_level', 'published')
    search_fields = ('name', 'type_id')
    list_filter = ('published', 'group__category__name', 'group__name')
    autocomplete_fields = ('group',) # Add autocomplete

# Register the snapshot to view in admin
@admin.register(PilotSnapshot)
class PilotSnapshotAdmin(admin.ModelAdmin):
    list_display = ('character', 'last_updated', 'get_total_sp')
    search_fields = ('character__character_name',)
    readonly_fields = ('character', 'skills_json', 'implants_json', 'last_updated')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Allow changing, but fields are read-only
        return True

    def has_delete_permission(self, request, obj=None):
        return True