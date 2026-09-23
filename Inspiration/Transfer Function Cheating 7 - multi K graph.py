import numpy as np
import matplotlib.pyplot as plt
import control as ctl
import os


# Function to get input from the user or use defaults
def get_input(prompt, default=None, dtype=float):
    response = input(prompt)
    if response.lower() == "no":
        return default
    try:
        return dtype(response)
    except ValueError:
        return default

# Function to format and print step response info
def print_step_info(info, system_name=""):
    print(f"\nStep Response Info for {system_name}:")
    for key, value in info.items():
        print(f"{key.replace('_', ' ').title()}: {value}")

# Step 1.1: Ask for the transfer function numerator and denominator
print("Let's define the transfer function G(s):")
numerator_str = input("Enter the numerator coefficients of the transfer function G(s) (comma-separated): ")
denominator_str = input("Enter the denominator coefficients of the transfer function G(s) (comma-separated): ")

# Convert input strings to lists of floats
numerator = [float(x) for x in numerator_str.split(',')]
denominator = [float(x) for x in denominator_str.split(',')]

# Create the transfer function G(s)
G = ctl.TransferFunction(numerator, denominator)

# Step 2: Ask for the input value for the step response
input_value = get_input("Enter the input value for the step response (default is 1): ", 1.0)

# Step 3: Ask if the user wants to compute step response with custom initial conditions
initial_conditions = None
initial_value = get_input("Enter the initial value for the step response (default is 0): ", 0.0)

# Step 4: Get feedback control values
use_feedback = input("Do you want to close the loop with a feedback system? (yes/no): ").lower()
if use_feedback == "yes":
    C_numerator_str = input("Enter the numerator coefficients of the non-proportional controller C(s) (comma-separated):\n ")
    C_denominator_str = input("Enter the denominator coefficients non proportional controller C(s)) (comma-separated):\n ")
    K_mult_str=input("Single or Multiple K Graph? S/M")
    multi = False
    if K_mult_str == "S" or K_mult_str == "s":
        K = get_input("Enter the gain K for the controller (default is 1): ", 1.0)
    if K_mult_str == "M" or K_mult_str == "m":
        K_m_str = input("Enter the different values of K (comma-separated):\n")
        K_m = [float(x) for x in K_m_str.split(',')]
        K = K_m[0]
        multi = True
    H = get_input("Enter the feedback transfer function H(s) (default is 1): ", 1.0)
    C_numerator = [float(x) for x in C_numerator_str.split(',')]
    C_denominator=[float(x) for x in C_denominator_str.split(',')]
    # Create closed-loop system
    C = ctl.TransferFunction(C_numerator, C_denominator)
    if multi == False:
        closed_loop = ctl.feedback(K*C*G, H)
    if multi == True:
        closed_loop = [ctl.feedback(M*C*G, H) for M in K_m]
else:
    closed_loop = None

# Step 5: Analyze and plot poles and zeros
poles = ctl.poles(G)
zeros = ctl.zeros(G)

O_natural_frequencies = []
O_damping_ratios = []
O_time_constants = []

for p in poles:
    real_part = np.real(p)
    imag_part = np.imag(p)
    
    # Natural Frequency (omega_n)
    omega_n = np.sqrt(real_part**2 + imag_part**2)
    O_natural_frequencies.append(omega_n)
    
    # Damping Ratio (zeta)
    if omega_n != 0:
        zeta = -real_part / omega_n
        O_damping_ratios.append(zeta)
    else:
        O_damping_ratios.append(float('nan'))  # If omega_n is zero, the system is undamped
    
    # Time Constant (tau), only for real parts
    if real_part != 0:
        tau = -1 / real_part
        O_time_constants.append(tau)
    else:
        O_time_constants.append(float('inf'))  # If real part is 0, time constant is infinite

print(u'\u2500' * 80)
print(f"Open Loop Poles:\n")
for i, pole in enumerate(poles):
    print(f"Open Loop Pole {i+1}: {pole}")
    print(f"  Natural Frequency (ωn): {O_natural_frequencies[i]}")
    print(f"  Damping Ratio (ζ): {O_damping_ratios[i]}")
    print(f"  Time Constant (τ): {O_time_constants[i]}")
    print()

# Plot poles and zeros
plt.figure()
if poles.size > 0:
    plt.scatter(np.real(poles), np.imag(poles), marker='x', color='red', label='Poles')
else:
    print("No poles to plot.")
if zeros.size > 0:
    plt.scatter(np.real(zeros), np.imag(zeros), marker='o', color='blue', label='Zeros')
else:
    print("No zeros to plot.")

plt.axhline(0, color='black', linestyle='--')
plt.axvline(0, color='black', linestyle='--')
plt.title("Poles and Zeros of Open-Loop G(s)")
plt.xlabel("Real")
plt.ylabel("Imaginary")
plt.xlim([np.min(np.real(poles)) - 1 if poles.size > 0 else -1, np.max(np.real(poles)) + 1 if poles.size > 0 else 1])
plt.ylim([np.min(np.imag(poles)) - 1 if poles.size > 0 else -1, np.max(np.imag(poles)) + 1 if poles.size > 0 else 1])
plt.legend()
plt.grid(True)

if closed_loop:
    if multi:
        cl_temp = closed_loop
        closed_loop = closed_loop[0]
    poles_closed = ctl.poles(closed_loop)
    zeros_closed = ctl.zeros(closed_loop)

    C_natural_frequencies = []
    C_damping_ratios = []
    C_time_constants = []

    for p in poles_closed:
        C_real_part = np.real(p)
        C_imag_part = np.imag(p)
    
        # Natural Frequency (omega_n)
        omega_n = np.sqrt(C_real_part**2 + C_imag_part**2)
        C_natural_frequencies.append(omega_n)
    
        # Damping Ratio (zeta)
        if omega_n != 0:
            zeta = -C_real_part / omega_n
            C_damping_ratios.append(zeta)
        else:
            C_damping_ratios.append(float('nan'))  # If omega_n is zero, the system is undamped
    
        # Time Constant (tau), only for real parts
        if C_real_part != 0:
            tau = -1 / C_real_part
            C_time_constants.append(tau)
        else:
            C_time_constants.append(float('inf'))  # If real part is 0, time constant is infinite

    print(u'\u2500' * 80)
    print(f"Closed Loop Poles:\n")
    for i, pole in enumerate(poles_closed):
        print(f"Closed Loop Pole {i+1}: {pole}")
        print(f"  Natural Frequency (ωn): {C_natural_frequencies[i]}")
        print(f"  Damping Ratio (ζ): {C_damping_ratios[i]}")
        print(f"  Time Constant (τ): {C_time_constants[i]}")
        print()

    plt.figure()
    if poles_closed.size > 0:
        plt.scatter(np.real(poles_closed), np.imag(poles_closed), marker='x', color='red', label='Poles')
    else:
        print("No closed-loop poles to plot.")
    if zeros_closed.size > 0:
        plt.scatter(np.real(zeros_closed), np.imag(zeros_closed), marker='o', color='blue', label='Zeros')
    else:
        print("No closed-loop zeros to plot.")
    
    plt.axhline(0, color='black', linestyle='--')
    plt.axvline(0, color='black', linestyle='--')
    plt.title(f"Poles and Zeros of Closed-Loop System for K = {K}")
    plt.xlabel("Real")
    plt.ylabel("Imaginary")
    plt.xlim([np.min(np.real(poles_closed)) - 1 if poles_closed.size > 0 else -1, np.max(np.real(poles_closed)) + 1 if poles_closed.size > 0 else 1])
    plt.ylim([np.min(np.imag(poles_closed)) - 1 if poles_closed.size > 0 else -1, np.max(np.imag(poles_closed)) + 1 if poles_closed.size > 0 else 1])
    plt.legend()
    plt.grid(True)


    
    if multi:
        closed_loop = cl_temp

# Step 6: Plot the step response with custom input value
try:
    t, y = ctl.step_response(G, T=None)
    default_step_value = 1.0  # Assuming the default step input is 1
    scaled_y = y * (input_value / default_step_value)
    final_y = scaled_y + initial_value

    plt.figure()
    plt.plot(t, final_y)
    plt.title(f'Step Response of G(s) to Input = {input_value}')
    plt.xlabel('Time (s)')
    plt.ylabel('Response')
    plt.grid(True)
except Exception as e:
    print(f"Error during step response computation: {e}")

# Step 7: Show closed-loop step response (if applicable)
if closed_loop:
    try:
        if multi:
            # For multiple K values, plot multiple step responses on the same graph
            plt.figure()
            for i, system in enumerate(closed_loop):
                t_cl, y_cl = ctl.step_response(system, T=None)
                scaled_y_cl = y_cl * (input_value / default_step_value)
                final_y_cl = scaled_y_cl + initial_value
                plt.plot(t_cl, final_y_cl, label=f'K = {K_m[i]}')

            plt.title(f'Closed-Loop Step Response to Input = {input_value}')
            plt.xlabel('Time (s)')
            plt.ylabel('Response')
            plt.grid(True)
            plt.legend()  # Add a legend to distinguish the lines for different K values
        else:
            # For a single K value, plot the step response as usual
            t_cl, y_cl = ctl.step_response(closed_loop, T=None)
            scaled_y_cl = y_cl * (input_value / default_step_value)
            final_y_cl = scaled_y_cl + initial_value

            plt.figure()
            plt.plot(t_cl, final_y_cl)
            plt.title(f'Closed-Loop Step Response to Input = {input_value}')
            plt.xlabel('Time (s)')
            plt.ylabel('Response')
            plt.grid(True)
        
        # Show the plot after plotting the responses
        plt.show()

    except Exception as e:
        print(f"Error during closed-loop step response computation: {e}")


# Step 8: Display step response information
try:
    info_open = ctl.step_info(G)
    print_step_info(info_open, "Open-Loop System")
except Exception as e:
    print(f"Error obtaining step response info for open-loop system: {e}")

if closed_loop:
    try:
        info_closed = ctl.step_info(closed_loop)
        print_step_info(info_closed, "Closed-Loop System")
    except Exception as e:
        print(f"Error obtaining step response info for closed-loop system: {e}")

# Step 9: Compute and display error 

    print(u'\u2500' * 80)
    print(f"Steady state error:\n")
    try:
        error_open = 1 - info_open['SteadyStateValue']
        print(f"\nOpen-loop steady-state error: {error_open:.4f}")
        
        if closed_loop:
            error_closed = 1 - info_closed['SteadyStateValue']
            print(f"Closed-loop steady-state error: {error_closed:.4f}")
    except Exception as e:
        print(f"Error computing steady-state error: {e}")

# Show plots
plt.show()
