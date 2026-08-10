class CleanHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if 'HTTP_HOST' in request.META:
            host = request.META['HTTP_HOST']
            if ',' in host:
                clean_host = host.split(',')[0].strip()
                if ':' in clean_host:
                    clean_host = clean_host.split(':')[0]
                request.META['HTTP_HOST'] = clean_host
                request.META['SERVER_NAME'] = clean_host
        return self.get_response(request)
