from gs1_datamatrix import GS1DataMatrixGenerator

def main():
    # Создаем экземпляр генератора
    generator = GS1DataMatrixGenerator(output_dir="generated_codes")
    
    # Пример генерации из GS1 строки
    gs1_string = "0104603757996235 215X09mURooMGUg 91EE10 92b4wYepTreVa2N0cvArPX0n2LNc7MDs/B52dJFOAxl3M="
    image = generator.generate_from_string(gs1_string)
    image.save("1.png")


if __name__ == "__main__":
    main()
