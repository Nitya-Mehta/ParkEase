from django.conf import settings
from django.core.mail import send_mail


def notification_channel_text(
    result,
    success_text='Email sent.',
    drafted_text='Email draft shown in terminal.',
    failure_text='Email could not be sent.',
):
    if result.get('email_sent'):
        return success_text
    if result.get('email_drafted'):
        return drafted_text
    return failure_text


def draft_email_list(recipients, subject, message):
    draft_to = [email for email in recipients if email]
    if not draft_to:
        return {'email_sent': False, 'email_drafted': False}

    print_email_draft(draft_to, subject, message)
    return {'email_sent': False, 'email_drafted': True}


def send_real_email_list(recipients, subject, message):
    recipient_list = [email for email in recipients if email]
    if not recipient_list:
        return {'email_sent': False, 'email_drafted': False}

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'ParkEase <noreply@parkease.local>'),
            recipient_list=recipient_list,
            fail_silently=False,
        )
        return {'email_sent': True, 'email_drafted': False}
    except Exception:
        return {'email_sent': False, 'email_drafted': False}


def send_real_user_email(user, subject, message):
    recipient = getattr(user, 'email', '') or f'{user.username} <no email set>'
    return send_real_email_list([recipient], subject, message)


def print_email_draft(recipients, subject, message):
    print('\n' + '=' * 72)
    print('PARKEASE EMAIL DRAFT')
    print(f'From: {getattr(settings, "DEFAULT_FROM_EMAIL", "ParkEase <noreply@parkease.local>")}')
    print(f'To: {", ".join(recipients)}')
    print(f'Subject: {subject}')
    print('-' * 72)
    print(message)
    print('=' * 72 + '\n')
