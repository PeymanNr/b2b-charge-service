from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from django.contrib import messages
from .models import CreditRequest
from .services import CreditService
from utils.enums import CreditRequestStatus
from utils.security_managers import SecurityAuditLogger

audit_logger = SecurityAuditLogger()


@admin.register(CreditRequest)
class CreditRequestAdmin(admin.ModelAdmin):
    """Enhanced admin interface for credits requests with security features"""

    list_display = [
        'id', 'vendor_name', 'amount_display', 'status_badge',
        'created_at', 'updated_at', 'admin_actions'
    ]
    list_filter = ['status', 'created_at', 'vendor']
    search_fields = ['vendor__name', 'amount']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']

    fieldsets = (
        ('اطلاعات درخواست', {
            'fields': ('vendor', 'amount', 'status')
        }),
        ('جزئیات بیشتر', {
            'fields': ('rejection_reason', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def vendor_name(self, obj):
        """Display vendor name with link"""
        if obj.vendor:
            url = reverse('admin:vendors_vendor_change', args=[obj.vendor.pk])
            return format_html('<a href="{}">{}</a>', url, obj.vendor.name)
        return '-'
    vendor_name.short_description = 'vendor'

    def amount_display(self, obj):
        """Display amount with currency"""
        return f"{obj.amount:,.0f} تومان"
    amount_display.short_description = 'amount'

    def status_badge(self, obj):
        """Display status with colored badge"""
        colors = {
            CreditRequestStatus.PENDING.value: '#ff9800',
            CreditRequestStatus.APPROVED.value: '#4caf50',
            CreditRequestStatus.REJECTED.value: '#f44336',
        }
        color = colors.get(obj.status, '#666')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'status'

    def admin_actions(self, obj):
        """Display admin action buttons"""
        if obj.status == CreditRequestStatus.PENDING.value:
            approve_url = reverse('admin:credit_approve_request', args=[obj.pk])
            reject_url = reverse('admin:credit_reject_request', args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" style="background: #4caf50; color: white; '
                'padding: 5px 10px; text-decoration: none; margin-right: 5px; border-radius: 3px;">Approve</a>'
                '<a class="button" href="{}" style="background: #f44336; color: white; '
                'padding: 5px 10px; text-decoration: none; border-radius: 3px;">Reject</a>',
                approve_url, reject_url
            )
        elif obj.status == CreditRequestStatus.APPROVED.value:
            return format_html(
                '<span style="color: #4caf50; font-weight: bold;">✓ Approved</span>'
            )
        elif obj.status == CreditRequestStatus.REJECTED.value:
            return format_html(
                '<span style="color: #f44336; font-weight: bold;">✗ Rejected</span>'
            )
        return '-'
    admin_actions.short_description = 'Operations'

    def get_urls(self):
        """Add custom URLs for approve/reject actions"""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                'approve/<uuid:request_id>/',
                self.admin_site.admin_view(self.approve_request_view),
                name='credit_approve_request',
            ),
            path(
                'reject/<uuid:request_id>/',
                self.admin_site.admin_view(self.reject_request_view),
                name='credit_reject_request',
            ),
        ]
        return custom_urls + urls

    def approve_request_view(self, request, request_id):
        """Handle credits request approval"""
        try:
            # Use secure service layer for approval
            success, message = CreditService.approve_credit_request(
                request_id=request_id,
                admin_user=request.user
            )

            if success:
                messages.success(request, f'✅ {message}')
                audit_logger.log_security_event(
                    'ADMIN_CREDIT_APPROVAL',
                    None,
                    {
                        'request_id': str(request_id),
                        'admin_user': request.user.username,
                        'success': True
                    },
                    'INFO'
                )
            else:
                messages.error(request, f'❌ {message}')
                audit_logger.log_security_event(
                    'ADMIN_CREDIT_APPROVAL_FAILED',
                    None,
                    {
                        'request_id': str(request_id),
                        'admin_user': request.user.username,
                        'error': message
                    },
                    'WARNING'
                )

        except Exception as e:
            messages.error(request, f'خطای سیستم: {str(e)}')
            audit_logger.log_security_event(
                'ADMIN_CREDIT_APPROVAL_ERROR',
                None,
                {
                    'request_id': str(request_id),
                    'admin_user': request.user.username,
                    'error': str(e)
                },
                'ERROR'
            )

        return HttpResponseRedirect(reverse('admin:credits_creditrequest_changelist'))

    def reject_request_view(self, request, request_id):
        """Handle credits request rejection"""
        if request.method == 'POST':
            reason = request.POST.get('reason', '').strip()
            if not reason:
                messages.error(request, 'دلیل رد درخواست الزامی است')
                return self._show_reject_form(request, request_id)

            try:
                # Use secure service layer for rejection
                success, message = CreditService.reject_credit_request(
                    request_id=request_id,
                    admin_user=request.user,
                    reason=reason
                )

                if success:
                    messages.success(request, f'✅ {message}')
                    audit_logger.log_security_event(
                        'ADMIN_CREDIT_REJECTION',
                        None,
                        {
                            'request_id': str(request_id),
                            'admin_user': request.user.username,
                            'reason': reason,
                            'success': True
                        },
                        'INFO'
                    )
                else:
                    messages.error(request, f'❌ {message}')

            except Exception as e:
                messages.error(request, f'خطای سیستم: {str(e)}')
                audit_logger.log_security_event(
                    'ADMIN_CREDIT_REJECTION_ERROR',
                    None,
                    {
                        'request_id': str(request_id),
                        'admin_user': request.user.username,
                        'error': str(e)
                    },
                    'ERROR'
                )

            return HttpResponseRedirect(reverse('admin:credits_creditrequest_changelist'))

        return self._show_reject_form(request, request_id)

    def _show_reject_form(self, request, request_id):
        """Show rejection form"""
        from django.shortcuts import render
        try:
            credit_request = CreditRequest.objects.get(id=request_id)
            context = {
                'credit_request': credit_request,
                'request_id': request_id,
                'title': f'رد درخواست اعتبار - {credit_request.vendor.name}',
                'opts': self.model._meta,
                'has_change_permission': True,
            }
            return render(request, 'admin/credits/reject_form.html', context)
        except CreditRequest.DoesNotExist:
            messages.error(request, 'درخواست اعتبار یافت نشد')
            return HttpResponseRedirect(reverse('admin:credits_creditrequest_changelist'))

    actions = ['bulk_approve_requests', 'bulk_reject_requests']

    def bulk_approve_requests(self, request, queryset):
        """Bulk approve pending credits requests"""
        pending_requests = queryset.filter(status=CreditRequestStatus.PENDING.value)
        approved_count = 0
        failed_count = 0

        for credit_request in pending_requests:
            success, message = CreditService.approve_credit_request(
                credit_request.id, request.user
            )
            if success:
                approved_count += 1
            else:
                failed_count += 1

        if approved_count > 0:
            messages.success(
                request,
                f'✅ {approved_count} درخواست با موفقیت تایید شد'
            )
        if failed_count > 0:
            messages.warning(
                request,
                f'⚠️ {failed_count} درخواست تایید نشد'
            )

        audit_logger.log_security_event(
            'ADMIN_BULK_CREDIT_APPROVAL',
            None,
            {
                'admin_user': request.user.username,
                'approved_count': approved_count,
                'failed_count': failed_count
            },
            'INFO'
        )

    bulk_approve_requests.short_description = 'تایید درخواست‌های انتخاب شده'

    def bulk_reject_requests(self, request, queryset):
        """Bulk reject pending credits requests"""
        pending_requests = queryset.filter(status=CreditRequestStatus.PENDING.value)
        rejected_count = 0

        for credit_request in pending_requests:
            success, message = CreditService.reject_credit_request(
                credit_request.id, request.user, "رد گروهی توسط ادمین"
            )
            if success:
                rejected_count += 1

        if rejected_count > 0:
            messages.success(
                request,
                f'✅ {rejected_count} درخواست رد شد'
            )

        audit_logger.log_security_event(
            'ADMIN_BULK_CREDIT_REJECTION',
            None,
            {
                'admin_user': request.user.username,
                'rejected_count': rejected_count
            },
            'INFO'
        )

    bulk_reject_requests.short_description = 'رد درخواست‌های انتخاب شده'
