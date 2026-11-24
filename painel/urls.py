from django.urls import path

from painel import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("configuracoes/", views.configuracoes, name="configuracoes"),
    path("configuracoes/credenciais/", views.salvar_credenciais, name="salvar_credenciais"),
    path("configuracoes/testar-modelos/", views.testar_modelos, name="testar_modelos"),
    path("modelos/", views.modelos, name="modelos"),
    path("juiz/", views.juiz, name="juiz"),
    path("indices/", views.indices, name="indices"),
    path("indices/novo/", views.novo_indice, name="novo_indice"),
    path("indices/<str:nome>/", views.indice, name="indice"),
    path("indices/<str:nome>/ativar/", views.ativar_indice, name="ativar_indice"),
    path("testes/busca/", views.busca, name="busca"),
    path("testes/comparar/", views.comparar, name="comparar"),
    path("testes/historico/", views.HistoricoView.as_view(), name="historico"),
    path("testes/historico/<int:pk>/", views.ExecucaoView.as_view(), name="execucao"),
    path("gabarito/", views.GabaritoView.as_view(), name="gabarito"),
    path("gabarito/nova/", views.NovaQuestaoView.as_view(), name="nova_questao"),
    path("gabarito/importar/", views.importar_gabarito, name="importar_gabarito"),
    path("gabarito/importar/confirmar/", views.confirmar_importacao, name="confirmar_importacao"),
    path("gabarito/<int:pk>/", views.EditarQuestaoView.as_view(), name="questao"),
    path("gabarito/<int:pk>/excluir/", views.ExcluirQuestaoView.as_view(), name="excluir_questao"),
    path("gabarito/rodadas/", views.rodadas, name="rodadas"),
    path("gabarito/rodadas/exportar/", views.exportar_rodadas, name="exportar_rodadas"),
    path("gabarito/rodadas/<int:pk>/", views.RodadaView.as_view(), name="rodada"),
    path("gabarito/rodadas/<int:pk>/avaliar/", views.avaliar_rodada, name="avaliar_rodada"),
]
