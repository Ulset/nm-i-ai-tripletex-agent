"""Sample 'create employee' prompts in all 7 supported languages.

Each prompt includes a name with special characters relevant to that language.
"""

SAMPLE_PROMPTS = {
    "nb": {
        "prompt": "Opprett en ansatt med navn Bjørn Ødegård og e-post bjorn@eksempel.no",
        "expected_first_name": "Bjørn",
        "expected_last_name": "Ødegård",
        "language": "Norwegian Bokmål",
    },
    "nn": {
        "prompt": "Opprett ein tilsett med namn Åse Bråthen og e-post aase@eksempel.no",
        "expected_first_name": "Åse",
        "expected_last_name": "Bråthen",
        "language": "Norwegian Nynorsk",
    },
    "en": {
        "prompt": "Create an employee named François O'Brien with email francois@example.com",
        "expected_first_name": "François",
        "expected_last_name": "O'Brien",
        "language": "English",
    },
    "es": {
        "prompt": "Crear un empleado con nombre José Muñoz y correo jose@ejemplo.es",
        "expected_first_name": "José",
        "expected_last_name": "Muñoz",
        "language": "Spanish",
    },
    "pt": {
        "prompt": "Criar um funcionário com nome João Gonçalves e e-mail joao@exemplo.pt",
        "expected_first_name": "João",
        "expected_last_name": "Gonçalves",
        "language": "Portuguese",
    },
    "de": {
        "prompt": "Erstellen Sie einen Mitarbeiter mit dem Namen Jürgen Müller und E-Mail juergen@beispiel.de",
        "expected_first_name": "Jürgen",
        "expected_last_name": "Müller",
        "language": "German",
    },
    "fr": {
        "prompt": "Créer un employé nommé Réné Lefèvre avec l'email rene@exemple.fr",
        "expected_first_name": "Réné",
        "expected_last_name": "Lefèvre",
        "language": "French",
    },
}
