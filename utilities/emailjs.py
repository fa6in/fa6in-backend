"""
utilities/emailjs.py

Envoi de l'email contenant le code de réinitialisation du mot de passe.
Tente d'abord EmailJS (REST API), puis retombe sur le SMTP Gmail configuré
dans settings.py si EmailJS échoue ou n'est pas configuré.
"""

import logging

import httpx
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

EMAILJS_API_URL = 'https://api.emailjs.com/api/v1.0/email/send'


def _send_via_emailjs(user, code):
    service_id = getattr(settings, 'EMAILJS_SERVICE_ID', None)
    template_id = getattr(settings, 'EMAILJS_TEMPLATE_ID', None)
    public_key = getattr(settings, 'EMAILJS_USER_ID', None)
    private_key = getattr(settings, 'EMAILJS_PRIVATE_KEY', None)

    if not all([service_id, template_id, public_key, private_key]):
        return False

    validity_minutes = getattr(settings, 'PASSWORD_RESET_CODE_VALIDITY_MINUTES', 10)

    payload = {
        'service_id': service_id,
        'template_id': template_id,
        'user_id': public_key,
        'accessToken': private_key,
        'template_params': {
            # Variables utilisées dans le corps du template EmailJS.
            'reset_code': code,
            'user_name': user.get_full_name() or user.username,
            'app_name': 'Ed-Tech',
            'expiry_minutes': validity_minutes,
            # Alias multiples pour le champ "To Email" du template (configuré
            # séparément dans le dashboard EmailJS, hors du corps HTML) :
            # on couvre les conventions les plus courantes.
            'to_email': user.email,
            'email': user.email,
            'user_email': user.email,
            'reply_to': user.email,
            'to_name': user.get_full_name() or user.username,
            'name': user.get_full_name() or user.username,
        },
    }

    try:
        response = httpx.post(EMAILJS_API_URL, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        logger.warning(
            "EmailJS a répondu avec le statut %s: %s",
            response.status_code, response.text,
        )
        return False
    except httpx.HTTPError:
        logger.exception("Échec de l'envoi de l'email via EmailJS.")
        return False


def _send_via_smtp(user, code):
    context = {
        'user': user,
        'code': code,
        'validity_minutes': getattr(settings, 'PASSWORD_RESET_CODE_VALIDITY_MINUTES', 10),
    }
    html_content = render_to_string('emails/password_reset_code.html', context)
    text_content = strip_tags(html_content)

    try:
        email = EmailMultiAlternatives(
            subject="Code de réinitialisation de mot de passe",
            body=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER),
            to=[user.email],
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Échec de l'envoi de l'email via SMTP.")
        return False


def send_password_reset_code_email(user, code):
    """
    Envoie le code de réinitialisation par email.
    Retourne True si l'email a été envoyé par au moins un canal.
    """
    if _send_via_emailjs(user, code):
        return True
    return _send_via_smtp(user, code)
