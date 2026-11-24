document.addEventListener("submit", (evento) => {
  const botao = evento.submitter;
  if (botao?.dataset.espera) {
    botao.setAttribute("aria-busy", "true");
    botao.textContent = botao.dataset.espera;
  }
});

const resultados = document.querySelectorAll("[data-trecho]");
resultados.forEach((botao) => {
  botao.addEventListener("click", () => {
    resultados.forEach((outro) => outro.setAttribute("aria-pressed", outro.dataset.trecho === botao.dataset.trecho));
    document.querySelectorAll("[data-leitura]").forEach((painel) => {
      painel.hidden = painel.dataset.leitura !== botao.dataset.trecho;
    });
  });
});

const tabelaAjustes = document.querySelector("[data-ajustes]");
if (tabelaAjustes) {
  const mostrarIguais = document.querySelector("#mostrar-iguais");
  const valorDe = (campo) => (campo.type === "checkbox" ? campo.checked : campo.value);

  const atualizarAjustes = () => {
    const usadas = [...tabelaAjustes.querySelectorAll("[data-usar] input")].map((campo) => campo.checked);
    tabelaAjustes.querySelectorAll("[data-ajuste]").forEach((linha) => {
      const campos = [...linha.querySelectorAll("input, select")];
      const valores = campos.filter((_, indice) => usadas[indice]).map(valorDe);
      const diferente = new Set(valores).size > 1;
      const manter = "fixo" in linha.dataset || linha.querySelector(".errorlist");
      linha.classList.toggle("diferente", diferente);
      linha.hidden = !diferente && !manter && !mostrarIguais.checked;
    });
  };

  tabelaAjustes.addEventListener("input", atualizarAjustes);
  mostrarIguais.addEventListener("change", atualizarAjustes);
  atualizarAjustes();
}

document.querySelectorAll("[data-marcar-todas]").forEach((botao) => {
  const caixas = [...botao.form.querySelectorAll(`input[name="${botao.dataset.marcarTodas}"]`)];
  const atualizarRotulo = () => {
    botao.textContent = caixas.every((caixa) => caixa.checked) ? "Desmarcar todas" : "Marcar todas";
  };
  botao.addEventListener("click", () => {
    const marcar = !caixas.every((caixa) => caixa.checked);
    caixas.forEach((caixa) => (caixa.checked = marcar));
    atualizarRotulo();
  });
  caixas.forEach((caixa) => caixa.addEventListener("change", atualizarRotulo));
  atualizarRotulo();
});
