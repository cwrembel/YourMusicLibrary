import tkinter as tk

root = tk.Tk()
root.title("Testfenster")
root.geometry("300x200")

label = tk.Label(root, text="Hallo, tkinter läuft!", font=("Arial", 14))
label.pack(pady=50)

root.mainloop()
