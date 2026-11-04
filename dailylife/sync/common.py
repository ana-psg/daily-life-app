"""O que as partes da sincronização com o Google dividem: estado da tela e o erro da biblioteca."""

STATE = {"sincronizando": False, "erro": "", "conectando": False}

try:  # sem as bibliotecas do Google o app funciona, só sem sincronizar
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover
    HttpError = Exception
