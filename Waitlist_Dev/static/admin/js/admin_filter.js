/*
 * This script handles dependent autocomplete fields in the Django admin.
 * Specifically, it filters the "Attribute" field based on the selected "Group"
 * in the ItemComparisonRule add/change form.
 *
 * This version uses the select2:opening event to modify the AJAX
 * settings once, ensuring all requests (including pagination) are filtered.
 */

(function ($) {
    $(document).ready(function () {
        // Only run this code on the ItemComparisonRule add/change page
        if ($('body').hasClass('change-form') && $('#itemcomparisonrule_form').length) {

            var groupSelect = $('#id_group');
            var attributeSelect = $('#id_attribute');

            // Listen for the select2 widget to be opened
            attributeSelect.on('select2:opening', function (e) {
                // This event fires *before* the search box is created
                // We'll modify the ajax options *once* here.

                // Check if we've already modified it
                if ($(this).data('ajax-modified')) {
                    return;
                }

                var select2Instance = $(this).data('select2');
                if (select2Instance) {

                    // Get the original data function
                    // (select2's default data function just returns {term: params.term, page: params.page})
                    var originalDataFunc = select2Instance.opts.ajax.data || function (params) {
                        return {
                            term: params.term,
                            page: params.page
                        };
                    };

                    // Override the ajax.data function
                    select2Instance.opts.ajax.data = function (params) {
                        // Call the original data function to get base params
                        var data = originalDataFunc.call(this, params);

                        // Get the currently selected group ID
                        var groupId = groupSelect.val();

                        // Add our group_id to the request data if it exists
                        if (groupId) {
                            data.group_id = groupId;
                        }

                        return data;
                    };

                    // Mark as modified so we don't do this again
                    $(this).data('ajax-modified', true);
                } else {
                    console.error("Could not find Select2 instance on #id_attribute. Dependent dropdowns may not work.");
                }
            });

            // Add a change listener to the group select
            groupSelect.on('change', function () {
                // When the group changes, clear the attribute selection
                attributeSelect.val(null).trigger('change');
            });
        }
    });
})(django.jQuery);