import os
import shutil
import tempfile
import unittest
from pathlib import Path

from assistente.nucleo import memory

ROOT = Path(__file__).resolve().parent.parent


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(ROOT / "memory_example", Path(self.tmp) / "memory_example")
        self.old = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.tmp)

    def test_cria_memoria_a_partir_dos_modelos(self):
        memory.ensure()
        self.assertTrue(Path("memory/perfil.md").exists())
        self.assertTrue(Path("memory/regras.md").exists())

    def test_lembrar_listar_esquecer(self):
        memory.remember("Reuniões só depois das 14h")
        memory.remember("Boletos do banco são sempre importantes")
        notas = memory.list_notes()
        self.assertEqual(len(notas), 2)
        self.assertIn("Reuniões só depois das 14h", notas[0])
        removida = memory.forget(1)
        self.assertIn("Reuniões", removida)
        self.assertEqual(len(memory.list_notes()), 1)

    def test_esquecer_numero_invalido(self):
        with self.assertRaises(ValueError):
            memory.forget(5)

    def test_comentarios_nao_vao_para_o_prompt(self):
        memory.remember("Prefiro respostas curtas")
        bloco = memory.prompt_block()
        self.assertIn("Prefiro respostas curtas", bloco)
        self.assertNotIn("<!--", bloco)
        self.assertNotIn("memory_example", bloco)

    def test_arquivo_novo_entra_na_memoria(self):
        memory.ensure()
        Path("memory/projetos.md").write_text("# Projetos\n- Site da loja\n", encoding="utf-8")
        self.assertIn("Site da loja", memory.read_all())

    def test_limite_mantem_notas_recentes(self):
        memory.ensure()
        for i in range(400):
            memory.remember(f"nota numero {i} " + "x" * 30)
        texto = memory.read_all()
        self.assertLessEqual(len(texto), memory.MAX_CHARS + 600)
        self.assertIn("nota numero 399", texto)
        self.assertNotIn("nota numero 0 ", texto)


if __name__ == "__main__":
    unittest.main()
