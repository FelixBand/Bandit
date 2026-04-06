import tkinter as tk

root = tk.Tk()

version = "2.0.0"

# Setting some window properties
root.title(f"Bandit - Game Launcher v{version}")
#root.configure(background="yellow") # Maybe this can be transparent? Or dark mode + light mode toggle
root.minsize(200, 200)
#root.maxsize(500, 500) # No need for a max size
root.geometry("600x800+50+50")






root.mainloop() # Up and away!