# Configuracao de concorrencia do Painel Financeiro Cervejeiros.
# Um processo com threads evita duplicar a memoria em uma instancia de 512 MB
# e permite atender novas requisicoes enquanto outras aguardam o banco.
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
