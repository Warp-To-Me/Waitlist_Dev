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

# We can also register the snapshot if you want to see it
@admin.register(PilotSnapshot)
class PilotSnapshotAdmin(admin.ModelAdmin):
    list_display = ('character', 'last_updated', 'get_total_sp')
    search_fields = ('character__character_name',)