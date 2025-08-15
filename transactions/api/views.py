from rest_framework import viewsets
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from ..services import TransactionService
from .serializers import TransactionSerializer
from vendors.models import Vendor
from utils.security_managers import SecurityAuditLogger
from utils.enums import TransactionType
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from transactions.services import BalanceReconciliationService


logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class TransactionViewSet(viewsets.ViewSet):
    """
    Secure Transaction ViewSet using service layer
    URL: /api/vendor/transactions/ - vendor determined from JWT token
    """

    def list(self, request):
        """
        Get transaction history for the authenticated user's vendor with filtering and pagination

        Query Parameters:
        - transaction_type: 'CREDIT' or 'SALE' (optional)
        - start_date: YYYY-MM-DD format (optional)
        - end_date: YYYY-MM-DD format (optional)
        - page: page number (default: 1)
        - page_size: items per page (default: 20, max: 100)
        """
        try:
            # Get vendor from authenticated user
            try:
                vendor = Vendor.objects.get(user=request.user)
            except Vendor.DoesNotExist:
                audit_logger.log_security_event(
                    'UNAUTHORIZED_TRANSACTION_ACCESS',
                    request.user.id,
                    {'error': 'User has no vendor profile'},
                    'WARNING'
                )
                return Response({
                    'success': False,
                    'message': 'شما مجوز دسترسی به این بخش را ندارید'
                }, status=status.HTTP_404_NOT_FOUND)

            transaction_type = request.query_params.get('transaction_type')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            page = int(request.query_params.get('page', 1))
            page_size = min(int(request.query_params.get('page_size', 20)), 100)

            # Validate transaction type
            if transaction_type and transaction_type not in ['CREDIT', 'SALE']:
                return Response({
                    'success': False,
                    'message': 'نوع تراکنش نامعتبر است. مقادیر مجاز: CREDIT, SALE'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Parse dates
            parsed_start_date = None
            parsed_end_date = None

            if start_date:
                try:
                    parsed_start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                except ValueError:
                    return Response({
                        'success': False,
                        'message': 'فرمت تاریخ شروع نامعتبر است. فرمت صحیح: YYYY-MM-DD'
                    }, status=status.HTTP_400_BAD_REQUEST)

            if end_date:
                try:
                    parsed_end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                except ValueError:
                    return Response({
                        'success': False,
                        'message': 'فرمت تاریخ پایان نامعتبر است. فرمت صحیح: YYYY-MM-DD'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Validate date range
            if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
                return Response({
                    'success': False,
                    'message': 'تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Convert transaction type string to enum value
            transaction_type_value = None
            if transaction_type:
                if transaction_type == 'CREDIT':
                    transaction_type_value = TransactionType.CREDIT.value
                elif transaction_type == 'SALE':
                    transaction_type_value = TransactionType.SALE.value

            # Get transactions using service
            transactions_queryset = TransactionService.get_vendor_transactions(
                vendor_id=vendor.id,
                transaction_type=transaction_type_value,
                start_date=parsed_start_date,
                end_date=parsed_end_date
            )

            # Apply pagination
            paginator = Paginator(transactions_queryset, page_size)

            if page > paginator.num_pages and paginator.num_pages > 0:
                return Response({
                    'success': False,
                    'message': f'صفحه مورد نظر وجود ندارد. حداکثر صفحه: {paginator.num_pages}'
                }, status=status.HTTP_404_NOT_FOUND)

            page_obj = paginator.get_page(page)
            transactions = page_obj.object_list

            # Serialize transactions
            serializer = TransactionSerializer(transactions, many=True, context={'request': request})

            # Get transaction summary
            date_range = None
            if parsed_start_date or parsed_end_date:
                start = parsed_start_date or timezone.now().date() - timedelta(days=365 * 10)
                end = parsed_end_date or timezone.now().date()
                date_range = [start, end]

            summary = TransactionService.get_transaction_summary(
                vendor_id=vendor.id,
                date_range=date_range
            )

            # Get balance reconciliation
            reconciliation = BalanceReconciliationService.balance_reconciliation(vendor)

            # Log successful access
            audit_logger.log_security_event(
                'TRANSACTION_HISTORY_ACCESSED',
                vendor.id,
                {
                    'transaction_count': len(transactions),
                    'page': page,
                    'filters': {
                        'transaction_type': transaction_type,
                        'start_date': start_date,
                        'end_date': end_date
                    }
                },
                'INFO'
            )

            # Prepare response data with proper Decimal to string conversion
            response_data = {
                'success': True,
                'data': {
                    'transactions': serializer.data,
                    'pagination': {
                        'current_page': page,
                        'total_pages': paginator.num_pages,
                        'total_items': paginator.count,
                        'page_size': page_size,
                        'has_next': page_obj.has_next(),
                        'has_previous': page_obj.has_previous(),
                        'next_page': page + 1 if page_obj.has_next() else None,
                        'previous_page': page - 1 if page_obj.has_previous() else None
                    },
                    'summary': {
                        'credits': {
                            'total': summary['credits']['total'],  # Already string from service
                            'count': summary['credits']['count']
                        },
                        'sales': {
                            'total': summary['sales']['total'],  # Already string from service
                            'count': summary['sales']['count']
                        },
                        'net_balance': summary['net_balance']  # Already string from service
                    },
                    'balance_info': {
                        'current_balance': str(vendor.balance),
                        'calculated_balance': reconciliation['calculated_balance'],  # Already string from service
                        'is_consistent': reconciliation['is_consistent'],
                        'difference': reconciliation['difference']  # Already string from service
                    },
                    'filters_applied': {
                        'transaction_type': transaction_type,
                        'start_date': start_date,
                        'end_date': end_date,
                        'date_range_days': (parsed_end_date - parsed_start_date).days if parsed_start_date and parsed_end_date else None
                    }
                }
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            audit_logger.log_security_event(
                'TRANSACTION_HISTORY_ERROR',
                request.user.id if request.user.is_authenticated else None,
                {'error': str(e)},
                'ERROR'
            )
            logger.error(f"Error in TransactionViewSet.list: {str(e)}")

            return Response({
                'success': False,
                'message': 'خطای داخلی سرور رخ داده است'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def reconcile_vendor_balance(request, vendor_id):
    """
    API برای بررسی همخوانی موجودی یک فروشنده
    GET /api/transactions/reconcile/{vendor_id}/
    """
    try:
        from vendors.models import Vendor
        vendor = Vendor.objects.get(id=vendor_id)
        result = BalanceReconciliationService.balance_reconciliation(vendor)

        return Response({
            'success': True,
            'data': {
                'vendor_id': result['vendor_id'],
                'vendor_name': result['vendor_name'],
                'stored_balance': str(result['stored_balance']),
                'calculated_balance': str(result['calculated_balance']),
                'difference': str(result['difference']),
                'is_consistent': result['is_consistent'],
                'transaction_summary': {
                    'total_credits': str(result['transaction_summary']['total_credits']),
                    'total_sales': str(result['transaction_summary']['total_sales']),
                    'credit_count': result['transaction_summary']['credit_transactions_count'],
                    'sale_count': result['transaction_summary']['sale_transactions_count']
                },
                'checked_at': result['checked_at']
            },
            'message': 'بررسی موجودی فروشنده تکمیل شد'
        })

    except Vendor.DoesNotExist:
        return Response({
            'success': False,
            'error': 'فروشنده یافت نشد'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error in reconcile_vendor_balance API: {str(e)}")
        return Response({
            'success': False,
            'error': 'خطای سرور داخلی'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def reconcile_all_balances(request):
    """
    API برای بررسی همخوانی موجودی تمام فروشندگان
    GET /api/transactions/reconcile-all/
    """
    try:
        results = BalanceReconciliationService.reconcile_all_balances()

        # تبدیل Decimal به string برای JSON serialization
        vendor_results = []
        for vendor in results['vendor_results']:
            vendor_results.append({
                'vendor_id': vendor['vendor_id'],
                'vendor_name': vendor['vendor_name'],
                'stored_balance': str(vendor['stored_balance']),
                'calculated_balance': str(vendor['calculated_balance']),
                'difference': str(vendor['difference']),
                'is_consistent': vendor['is_consistent']
            })

        system_stats = results['summary']['system_stats']

        return Response({
            'success': True,
            'data': {
                'summary': {
                    'total_vendors': results['summary']['total_vendors'],
                    'consistent_vendors': results['summary']['consistent_vendors'],
                    'inconsistent_vendors': results['summary']['inconsistent_vendors'],
                    'consistency_percentage': round(results['summary']['consistency_percentage'], 2),
                    'total_difference': str(results['summary']['total_difference']),
                    'execution_time': round(results['summary']['execution_time'], 2),
                    'checked_at': results['summary']['checked_at']
                },
                'system_stats': {
                    'total_transactions': system_stats['total_transactions'],
                    'total_credits': str(system_stats['total_credits']),
                    'total_sales': str(system_stats['total_sales']),
                    'net_system_balance': str(system_stats['net_system_balance'])
                },
                'vendor_results': vendor_results
            },
            'message': 'بررسی همخوانی تمام فروشندگان تکمیل شد'
        })

    except Exception as e:
        logger.error(f"Error in reconcile_all_balances API: {str(e)}")
        return Response({
            'success': False,
            'error': 'خطای سرور داخلی'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def balance_report(request):
    """
    API برای تولید گزارش تفصیلی همخوانی
    GET /api/transactions/balance-report/?vendor_id=123&format=text
    """
    try:
        vendor_id = request.GET.get('vendor_id')
        format_type = request.GET.get('format', 'json')  # json یا text

        if vendor_id:
            vendor_id = int(vendor_id)

        if format_type == 'text':
            report = BalanceReconciliationService.generate_reconciliation_report(vendor_id)
            return HttpResponse(
                report,
                content_type='text/plain; charset=utf-8',
                headers={'Content-Disposition': 'attachment; filename="balance_report.txt"'}
            )
        else:
            # JSON format
            if vendor_id:
                from vendors.models import Vendor
                vendor = Vendor.objects.get(id=vendor_id)
                result = BalanceReconciliationService.balance_reconciliation(vendor)
                data = {'vendor_result': result}
            else:
                data = BalanceReconciliationService.reconcile_all_balances()

            return Response({
                'success': True,
                'data': data,
                'message': 'گزارش همخوانی تولید شد'
            })

    except ValueError:
        return Response({
            'success': False,
            'error': 'شناسه فروشنده نامعتبر است'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error in balance_report API: {str(e)}")
        return Response({
            'success': False,
            'error': 'خطای سرور داخلی'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
