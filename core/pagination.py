"""
core/pagination.py
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Pagination par défaut (20 éléments), que le client peut agrandir avec
    ?page_size= (ex : listes complètes de l'éditeur de contenu).
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 500
